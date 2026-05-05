from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import json
import configparser
import time
import threading
import re
import os

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.service import jobs, compute
from databricks.sdk.service.jobs import RunLifeCycleState, RunResultState
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src import __version__
from src.repositories.workflow_installations_repository import workflow_installation_repo
from src.repositories.workflow_job_runs_repository import workflow_job_run_repo
from src.repositories.workflow_configurations_repository import workflow_configuration_repo
from src.models.workflow_installations import WorkflowInstallation
from src.models.workflow_configurations import WorkflowParameterDefinition, WorkflowConfiguration, WorkflowConfigurationUpdate

logger = get_logger(__name__)


class JobsManager:
    def __init__(self, db: Session, ws_client: WorkspaceClient, *, workflows_root: Optional[Path] = None, notifications_manager=None, settings=None, workspace_deployer=None):
        self._db = db
        self._client = ws_client
        self._workflows_root = workflows_root or Path(__file__).parent.parent / "workflows"
        self._notifications_manager = notifications_manager
        self._settings = settings
        self._workspace_deployer = workspace_deployer
        self._running_jobs: Dict[int, str] = {}  # run_id -> notification_id
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_polling = threading.Event()

    def list_available_workflows(self) -> List[Dict[str, str]]:
        root = self._workflows_root
        if not root.exists():
            return []
        items: List[Dict[str, str]] = []
        for d in root.iterdir():
            if not d.is_dir():
                continue
            yaml_file = d / f"{d.name}.yaml"
            if not yaml_file.exists():
                continue
            name = d.name
            description = ""
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                    if isinstance(data, dict):
                        name = str(data.get("name", name))
                        if data.get("description"):
                            description = str(data.get("description"))
            except Exception:
                name = d.name
            items.append({"id": d.name, "name": name, "description": description})
        # Sort by name alphabetically
        return sorted(items, key=lambda x: x["name"].lower())

    def install_workflow(self, workflow_id: str, *, job_cluster_id: Optional[str] = None) -> int:
        # Deploy workflow code to workspace if deployer is configured
        if self._workspace_deployer:
            workflow_dir = self._workflows_root / workflow_id
            if workflow_dir.exists():
                self._workspace_deployer.deploy_workflow(workflow_id, workflow_dir)
                logger.info(f"Deployed workflow '{workflow_id}' to workspace")
        elif self._settings and self._settings.WORKSPACE_DEPLOYMENT_PATH:
            logger.error(
                f"WORKSPACE_DEPLOYMENT_PATH is set to '{self._settings.WORKSPACE_DEPLOYMENT_PATH}' "
                f"but WorkspaceDeployer is not initialized. Workflow files will NOT be uploaded. "
                f"The job will be created but will fail at runtime."
            )

        wf_def = self._get_workflow_definition(workflow_id, job_cluster_id=job_cluster_id)

        # Build job settings kwargs from workflow definition
        tasks = self._build_tasks_from_definition(wf_def)
        job_settings_kwargs = {
            'name': wf_def.get('name', workflow_id),
            'tasks': tasks  # Keep as Task objects
        }

        # If YAML defines environments, convert and include them
        if isinstance(wf_def.get('environments'), list):
            env_objs: List[jobs.JobEnvironment] = []
            for env in wf_def['environments']:
                if not isinstance(env, dict):
                    continue
                env_key = env.get('environment_key')
                spec_dict = env.get('spec') or {}
                
                # Convert dependencies list to proper format
                if 'dependencies' in spec_dict and isinstance(spec_dict['dependencies'], list):
                    # Dependencies should be a list of strings like ["pkg==1.0.0", ...]
                    # Create Environment with proper client version
                    # Note: compute.Environment doesn't support env_vars directly
                    # Environment variables need to be passed via spark_conf or job run parameters
                    spec_obj = compute.Environment(
                        client='1',  # Use default Databricks runtime
                        dependencies=spec_dict['dependencies']
                    )
                else:
                    # Try to create Environment from spec_dict as-is
                    try:
                        spec_obj = compute.Environment(**spec_dict)
                    except Exception:
                        # If it fails, pass as dict and let SDK handle it
                        spec_obj = spec_dict
                        
                env_objs.append(jobs.JobEnvironment(environment_key=env_key, spec=spec_obj))
            if env_objs:
                job_settings_kwargs['environments'] = env_objs

        # Check if any tasks need serverless (no cluster_id specified)
        # If so, add default environment for serverless compute
        has_serverless_tasks = any(
            not hasattr(task, 'existing_cluster_id') or task.existing_cluster_id is None
            for task in tasks
        )
        if has_serverless_tasks and 'environments' not in wf_def:
            # Add default serverless environment
            job_settings_kwargs['environments'] = [
                jobs.JobEnvironment(
                    environment_key='default',
                    spec=compute.Environment(
                        client='1'  # Use default Databricks runtime
                    )
                )
            ]
            # Set environment_key on tasks that don't have a cluster
            for task in tasks:
                if not hasattr(task, 'existing_cluster_id') or task.existing_cluster_id is None:
                    task.environment_key = 'default'

        # Add optional job configuration from YAML
        if 'schedule' in wf_def:
            schedule_config = wf_def['schedule']
            if isinstance(schedule_config, dict):
                job_settings_kwargs['schedule'] = jobs.CronSchedule(
                    quartz_cron_expression=schedule_config.get('quartz_cron_expression'),
                    timezone_id=schedule_config.get('timezone_id', 'UTC'),
                    pause_status=jobs.PauseStatus(schedule_config.get('pause_status', 'UNPAUSED'))
                )

        if 'continuous' in wf_def and wf_def['continuous']:
            job_settings_kwargs['continuous'] = jobs.Continuous(pause_status=jobs.PauseStatus.UNPAUSED)

        if 'parameters' in wf_def:
            params = wf_def['parameters']
            if isinstance(params, dict):
                # Convert dict to list of JobParameter objects with default values
                job_settings_kwargs['parameters'] = [
                    jobs.JobParameter(name=key, default=str(value))
                    for key, value in params.items()
                ]
            else:
                job_settings_kwargs['parameters'] = params

        if 'tags' in wf_def:
            job_settings_kwargs['tags'] = wf_def['tags']

        if 'timeout_seconds' in wf_def:
            job_settings_kwargs['timeout_seconds'] = int(wf_def['timeout_seconds'])

        if 'max_concurrent_runs' in wf_def:
            job_settings_kwargs['max_concurrent_runs'] = int(wf_def['max_concurrent_runs'])

        if 'email_notifications' in wf_def:
            email_config = wf_def['email_notifications']
            if isinstance(email_config, dict):
                job_settings_kwargs['email_notifications'] = jobs.JobEmailNotifications(
                    on_start=email_config.get('on_start', []),
                    on_success=email_config.get('on_success', []),
                    on_failure=email_config.get('on_failure', []),
                    no_alert_for_skipped_runs=email_config.get('no_alert_for_skipped_runs', False)
                )

        # Create the job directly with kwargs (no JobSettings intermediate object needed)
        created = self._client.jobs.create(**job_settings_kwargs)
        job_id = int(created.job_id)

        # Persist installation to database
        try:
            # Get workspace_id from settings if available
            workspace_id = None
            if self._settings and hasattr(self._settings, 'DATABRICKS_HOST'):
                # Use host as workspace identifier since DATABRICKS_WORKSPACE_ID doesn't exist
                workspace_id = self._settings.DATABRICKS_HOST

            installation = WorkflowInstallation(
                workflow_id=workflow_id,
                name=wf_def.get('name', workflow_id),
                job_id=job_id,
                workspace_id=workspace_id,
                status='installed',
                installed_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            workflow_installation_repo.create(self._db, obj_in=installation)
            self._db.commit()
            logger.info(f"Persisted installation record for workflow '{workflow_id}' with job_id {job_id}")
        except Exception as e:
            logger.error(f"Failed to persist installation record for workflow '{workflow_id}': {e}")
            self._db.rollback()
            # Don't fail the installation if DB persist fails, but log it

        return job_id

    def update_workflow(self, workflow_id: str, job_id: int, *, job_cluster_id: Optional[str] = None) -> None:
        wf_def = self._get_workflow_definition(workflow_id, job_cluster_id=job_cluster_id)
        
        # Build job settings with additional configuration options
        job_settings = jobs.JobSettings(
            name=wf_def.get('name'),
            tasks=self._build_tasks_from_definition(wf_def)
        )
        
        # Include environments if defined in YAML
        if isinstance(wf_def.get('environments'), list):
            env_objs: List[jobs.JobEnvironment] = []
            for env in wf_def['environments']:
                if not isinstance(env, dict):
                    continue
                env_key = env.get('environment_key')
                spec_dict = env.get('spec') or {}
                
                # Convert dependencies list to proper format
                if 'dependencies' in spec_dict and isinstance(spec_dict['dependencies'], list):
                    # Dependencies should be a list of strings like ["pkg==1.0.0", ...]
                    # Create Environment with proper client version
                    # Note: compute.Environment doesn't support env_vars directly
                    # Environment variables need to be passed via spark_conf or job run parameters
                    spec_obj = compute.Environment(
                        client='1',  # Use default Databricks runtime
                        dependencies=spec_dict['dependencies']
                    )
                else:
                    # Try to create Environment from spec_dict as-is
                    try:
                        spec_obj = compute.Environment(**spec_dict)
                    except Exception:
                        # If it fails, pass as dict and let SDK handle it
                        spec_obj = spec_dict
                        
                env_objs.append(jobs.JobEnvironment(environment_key=env_key, spec=spec_obj))
            if env_objs:
                job_settings.environments = env_objs

        # Add optional job configuration from YAML
        if 'schedule' in wf_def:
            schedule_config = wf_def['schedule']
            if isinstance(schedule_config, dict):
                cron_schedule = jobs.CronSchedule(
                    quartz_cron_expression=schedule_config.get('quartz_cron_expression'),
                    timezone_id=schedule_config.get('timezone_id', 'UTC'),
                    pause_status=jobs.PauseStatus(schedule_config.get('pause_status', 'UNPAUSED'))
                )
                job_settings.schedule = cron_schedule
        
        if 'continuous' in wf_def and wf_def['continuous']:
            job_settings.continuous = jobs.Continuous(pause_status=jobs.PauseStatus.UNPAUSED)
        
        if 'parameters' in wf_def:
            params = wf_def['parameters']
            if isinstance(params, dict):
                # Convert dict to list of JobParameter objects with default values
                job_settings.parameters = [
                    jobs.JobParameter(name=key, default=str(value))
                    for key, value in params.items()
                ]
            else:
                job_settings.parameters = params
        
        if 'tags' in wf_def:
            job_settings.tags = wf_def['tags']
        
        if 'timeout_seconds' in wf_def:
            job_settings.timeout_seconds = int(wf_def['timeout_seconds'])
        
        if 'max_concurrent_runs' in wf_def:
            job_settings.max_concurrent_runs = int(wf_def['max_concurrent_runs'])
        
        if 'email_notifications' in wf_def:
            email_config = wf_def['email_notifications']
            if isinstance(email_config, dict):
                job_settings.email_notifications = jobs.JobEmailNotifications(
                    on_start=email_config.get('on_start', []),
                    on_success=email_config.get('on_success', []),
                    on_failure=email_config.get('on_failure', []),
                    no_alert_for_skipped_runs=email_config.get('no_alert_for_skipped_runs', False)
                )
        
        self._client.jobs.update(job_id=job_id, new_settings=job_settings)

    def remove_workflow(self, job_id: int) -> None:
        self._client.jobs.delete(job_id=job_id)

        # Remove from database
        try:
            db_obj = workflow_installation_repo.get_by_job_id(self._db, job_id=job_id)
            if db_obj:
                workflow_installation_repo.remove(self._db, id=db_obj.id)
                self._db.commit()
                logger.info(f"Removed installation record for job_id {job_id}")
        except Exception as e:
            logger.error(f"Failed to remove installation record for job_id {job_id}: {e}")
            self._db.rollback()

    def run_job(self, job_id: int, job_name: Optional[str] = None, job_parameters: Optional[Dict[str, str]] = None, workflow_id: Optional[str] = None) -> int:
        """Run a job and create a progress notification.
        
        Args:
            job_id: Databricks job ID to run
            job_name: Optional job name for notifications
            job_parameters: Optional dict of parameter name->value for the job (ad-hoc overrides)
            workflow_id: Optional workflow ID to enable auto-injection of database params
        
        Returns:
            run_id: Databricks run ID
        """
        # Prepare run_now arguments
        run_now_kwargs = {"job_id": job_id}
        
        # Merge saved configuration with database params and ad-hoc params
        merged_params = {}
        if workflow_id:
            # Auto-inject database params and merge with any saved configuration
            merged_params = self.get_merged_job_parameters(workflow_id, ad_hoc_params=job_parameters)
        elif job_parameters:
            # No workflow_id provided, use ad-hoc params as-is
            merged_params = job_parameters
        
        # Add parameters if any exist
        if merged_params:
            run_now_kwargs["job_parameters"] = merged_params
        
        run = self._client.jobs.run_now(**run_now_kwargs)
        run_id = int(run.run_id)
        
        if self._notifications_manager:
            # Get job name if not provided
            if not job_name:
                job = self._client.jobs.get(job_id=job_id)
                job_name = job.settings.name if job.settings else f"Job {job_id}"
            
            # Create progress notification for admin users
            notification_id = self._create_job_progress_notification(job_name, run_id)
            self._running_jobs[run_id] = notification_id
            
            # Start monitoring thread
            monitor_thread = threading.Thread(
                target=self._monitor_job_progress,
                args=(run_id, job_name, notification_id),
                daemon=True
            )
            monitor_thread.start()
        
        return run_id

    def find_job_by_name(self, job_name: str) -> Optional[jobs.Job]:
        all_jobs = self._client.jobs.list()
        return next((job for job in all_jobs if job.settings.name == job_name), None)

    # --- Configuration Management ---
    
    def get_workflow_parameter_definitions(self, workflow_id: str) -> List[WorkflowParameterDefinition]:
        """Get parameter definitions from workflow YAML configurable_parameters section.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            List of parameter definitions from YAML
        """
        try:
            yaml_path = self._workflows_root / workflow_id / f"{workflow_id}.yaml"
            if not yaml_path.exists():
                logger.warning(f"Workflow YAML not found: {yaml_path}")
                return []
            
            with open(yaml_path) as f:
                data = yaml.safe_load(f) or {}
            
            config_params = data.get('configurable_parameters', [])
            if not isinstance(config_params, list):
                return []
            
            # Parse each parameter definition
            definitions = []
            for param_def in config_params:
                if not isinstance(param_def, dict):
                    continue
                try:
                    definitions.append(WorkflowParameterDefinition(**param_def))
                except Exception as e:
                    logger.warning(f"Invalid parameter definition in {workflow_id}: {e}")
                    continue
            
            return definitions
        except Exception as e:
            logger.error(f"Error reading parameter definitions for {workflow_id}: {e}")
            return []
    
    def get_workflow_configuration(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        """Get saved configuration for a workflow from database.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            Configuration dict or None if not found
        """
        return workflow_configuration_repo.get_configuration_dict(self._db, workflow_id=workflow_id)
    
    def update_workflow_configuration(self, workflow_id: str, configuration: Dict[str, Any]) -> WorkflowConfiguration:
        """Update workflow configuration in database.
        
        Args:
            workflow_id: Workflow identifier
            configuration: Parameter name -> value mapping
            
        Returns:
            Updated configuration
        """
        db_obj = workflow_configuration_repo.upsert(
            self._db,
            workflow_id=workflow_id,
            configuration=configuration
        )
        self._db.commit()
        
        # Return as Pydantic model
        config_dict = workflow_configuration_repo.get_configuration_dict(self._db, workflow_id=workflow_id)
        return WorkflowConfiguration(workflow_id=workflow_id, configuration=config_dict or {})
    
    def get_merged_job_parameters(self, workflow_id: str, ad_hoc_params: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Merge saved configuration with ad-hoc parameters for job execution.
        
        Saved configuration values are converted to strings and merged with ad-hoc parameters.
        Ad-hoc parameters take precedence over saved configuration.
        
        Also automatically injects system-level database connection parameters from settings.
        
        Args:
            workflow_id: Workflow identifier
            ad_hoc_params: Optional runtime parameters to override saved config
            
        Returns:
            Merged parameters dict (all values as strings for job submission)
        """
        merged: Dict[str, str] = {}
        
        # Load saved configuration
        saved_config = self.get_workflow_configuration(workflow_id)
        if saved_config:
            # Convert all values to strings for job parameters
            for key, value in saved_config.items():
                if isinstance(value, (list, dict)):
                    # Serialize complex types to JSON
                    merged[key] = json.dumps(value)
                elif value is None:
                    merged[key] = ""
                else:
                    merged[key] = str(value)
        
        # Inject system-level database connection parameters from settings
        # These are required for workflows that connect to the app's database
        if self._settings:
            # Get Lakebase identifier from app resources (same as database.py)
            lakebase_instance = ''
            try:
                from src.common.database import get_lakebase_info
                app_name = getattr(self._settings, 'DATABRICKS_APP_NAME', None)
                if app_name and self._client:
                    info = get_lakebase_info(app_name, self._client)
                    if info:
                        lakebase_instance = info.identifier
                        logger.info(f"Auto-detected Lakebase ({info.lakebase_type}): {lakebase_instance}")
                if not lakebase_instance:
                    logger.warning(f"Could not auto-detect Lakebase info for app '{app_name}'")
            except Exception as e:
                logger.warning(f"Failed to get Lakebase info: {e}")
            
            db_params = {
                'lakebase_instance_name': lakebase_instance,
                'postgres_host': str(getattr(self._settings, 'PGHOST', '') or ''),
                'postgres_db': str(getattr(self._settings, 'PGDATABASE', '') or ''),
                'postgres_port': str(getattr(self._settings, 'PGPORT', '5432') or '5432'),
                'postgres_schema': str(getattr(self._settings, 'PGSCHEMA', 'public') or 'public'),
                # Telemetry parameters for WorkspaceClient identification
                'product_name': 'ontos',
                'product_version': __version__,
            }
            # Only inject if workflow YAML defines these parameters
            try:
                wf_def = self._get_workflow_definition(workflow_id, job_cluster_id=None)
                wf_params = wf_def.get('parameters', {})
                if isinstance(wf_params, dict):
                    for param_name, param_value in db_params.items():
                        if param_name in wf_params:
                            # Only inject if not already set by user config
                            if param_name not in merged:
                                merged[param_name] = str(param_value)
            except Exception as e:
                logger.warning(f"Could not check workflow parameters for {workflow_id}: {e}")
        
        # Merge ad-hoc parameters (these override everything)
        if ad_hoc_params:
            merged.update(ad_hoc_params)
        
        return merged

    # --- internals ---
    def _get_workflow_definition(self, workflow_id: str, *, job_cluster_id: Optional[str]) -> Dict[str, Any]:
        base = self._workflows_root / workflow_id
        if not base.exists():
            raise ValueError(f"Workflow not found: {workflow_id}")
        yaml_path = base / f"{workflow_id}.yaml"
        ini_path = base / "job.ini"
        wf: Dict[str, Any]
        if yaml_path.exists():
            with open(yaml_path) as f:
                wf = yaml.safe_load(f) or {}
        elif ini_path.exists():
            config = configparser.ConfigParser()
            config.read(ini_path)
            wf = {
                "name": config.get("job", "name", fallback=workflow_id),
                "format": config.get("job", "format", fallback="MULTI_TASK"),
                "tasks": []
            }
            for section in config.sections():
                if not section.startswith("task:"):
                    continue
                tkey = section.split(":", 1)[1]
                task: Dict[str, Any] = {"task_key": tkey}
                nb = config.get(section, "notebook_path", fallback=None)
                if nb:
                    task["notebook_task"] = {"notebook_path": nb}
                wheel = config.get(section, "python_wheel_task", fallback=None)
                if wheel:
                    try:
                        task["python_wheel_task"] = json.loads(wheel)
                    except Exception:
                        logger.warning(f"Invalid python_wheel_task JSON in {ini_path} for {tkey}")
                wf["tasks"].append(task)
        else:
            raise ValueError(f"Workflow definition not found: {yaml_path} or {ini_path}")

        # Handle cluster configuration
        # If job_cluster_id is None, tasks will use Databricks serverless compute
        # by omitting cluster parameters (existing_cluster_id, new_cluster)
        if isinstance(wf.get("tasks"), list):
            for t in wf["tasks"]:
                if job_cluster_id:
                    # Set the configured cluster ID, overriding any placeholder
                    if "new_cluster" not in t:
                        t["existing_cluster_id"] = job_cluster_id
                else:
                    # Remove placeholder cluster IDs to enable serverless
                    if t.get("existing_cluster_id") in ["cluster-id", ""]:
                        del t["existing_cluster_id"]

        # Resolve relative paths to absolute workspace paths
        # Priority 1: Use WORKSPACE_DEPLOYMENT_PATH for containerized Apps
        # Priority 2: Use WORKSPACE_APP_PATH for local dev with remote jobs
        # Priority 3: Derive from __file__ (legacy, works when app runs in workspace)
        if self._settings and self._settings.WORKSPACE_DEPLOYMENT_PATH:
            # Use deployment path (for containerized Databricks Apps)
            base_path = self._settings.WORKSPACE_DEPLOYMENT_PATH
        elif self._settings and self._settings.WORKSPACE_APP_PATH:
            # Use configured workspace path (for local dev with remote jobs)
            base_path = self._settings.WORKSPACE_APP_PATH
        else:
            # Derive from __file__ (works when app runs in workspace)
            base_path = str(Path(__file__).parent.parent)

        # Helper: detect URI scheme like file:, dbfs:, s3:, etc.
        def _has_scheme(path: str) -> bool:
            return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*:', path))

        if isinstance(wf.get("tasks"), list):
            for t in wf["tasks"]:
                # Handle notebook_task
                if 'notebook_task' in t and isinstance(t['notebook_task'], dict):
                    notebook_path = t['notebook_task'].get('notebook_path', '')
                    if notebook_path and not notebook_path.startswith('/') and not _has_scheme(notebook_path):
                        # Convert to workspace path
                        # If using WORKSPACE_DEPLOYMENT_PATH, workflow is deployed directly there
                        # Otherwise, workflow is nested under src/workflows
                        if self._settings and self._settings.WORKSPACE_DEPLOYMENT_PATH:
                            workspace_path = f"{base_path}/{workflow_id}/{notebook_path}"
                        else:
                            workspace_path = f"{base_path}/workflows/{workflow_id}/{notebook_path}"
                        t['notebook_task']['notebook_path'] = workspace_path

                # Handle spark_python_task
                if 'spark_python_task' in t and isinstance(t['spark_python_task'], dict):
                    python_file = t['spark_python_task'].get('python_file', '')
                    if python_file and not python_file.startswith('/') and not _has_scheme(python_file):
                        # Convert to workspace path
                        # If using WORKSPACE_DEPLOYMENT_PATH, workflow is deployed directly there
                        # Otherwise, workflow is nested under src/workflows
                        if self._settings and self._settings.WORKSPACE_DEPLOYMENT_PATH:
                            workspace_path = f"{base_path}/{workflow_id}/{python_file}"
                        else:
                            workspace_path = f"{base_path}/workflows/{workflow_id}/{python_file}"
                        t['spark_python_task']['python_file'] = workspace_path

        return wf

    def _build_tasks_from_definition(self, wf: Dict[str, Any]) -> List[jobs.Task]:
        tasks: List[jobs.Task] = []
        # Determine default environment_key if environments are defined
        default_env_key: Optional[str] = None
        if isinstance(wf.get('environments'), list) and wf['environments']:
            first_env = wf['environments'][0]
            if isinstance(first_env, dict):
                default_env_key = first_env.get('environment_key')
        for t in wf.get('tasks', []) or []:
            if not isinstance(t, dict):
                continue
            kwargs: Dict[str, Any] = {}
            if 'task_key' in t:
                kwargs['task_key'] = t['task_key']
            # Only set cluster params if they exist in task definition
            # Omitting them enables Databricks serverless compute
            if 'existing_cluster_id' in t:
                kwargs['existing_cluster_id'] = t['existing_cluster_id']
            # Optional: map environment_key for serverless environments
            if 'environment_key' in t:
                kwargs['environment_key'] = t['environment_key']
            if 'notebook_task' in t and isinstance(t['notebook_task'], dict):
                kwargs['notebook_task'] = jobs.NotebookTask(**t['notebook_task'])
            if 'spark_python_task' in t and isinstance(t['spark_python_task'], dict):
                # Resolve ${ENV} placeholders in parameters
                spt = dict(t['spark_python_task'])
                params = spt.get('parameters')
                if isinstance(params, list):
                    resolved: List[Any] = []
                    for p in params:
                        if isinstance(p, str):
                            m = re.match(r'^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$', p)
                            if m:
                                var = m.group(1)
                                val = None
                                if self._settings and hasattr(self._settings, var):
                                    val = getattr(self._settings, var)
                                if val is None:
                                    val = os.environ.get(var)
                                p = str(val) if val is not None else p
                        resolved.append(p)
                    spt['parameters'] = resolved
                
                kwargs['spark_python_task'] = jobs.SparkPythonTask(**spt)
            if 'python_wheel_task' in t and isinstance(t['python_wheel_task'], dict):
                kwargs['python_wheel_task'] = jobs.PythonWheelTask(**t['python_wheel_task'])
            
            # Handle libraries if specified  
            if 'libraries' in t and isinstance(t['libraries'], list):
                lib_objs: List[Any] = []
                for lib in t['libraries']:
                    if not isinstance(lib, dict):
                        continue
                    # Support pypi, maven, jar, egg, whl formats
                    # Use compute.Library which is the proper SDK dataclass
                    if 'pypi' in lib and isinstance(lib['pypi'], dict):
                        pypi_spec = compute.PythonPyPiLibrary(**lib['pypi'])
                        lib_objs.append(compute.Library(pypi=pypi_spec))
                    elif 'maven' in lib and isinstance(lib['maven'], dict):
                        maven_spec = compute.MavenLibrary(**lib['maven'])
                        lib_objs.append(compute.Library(maven=maven_spec))
                    elif 'jar' in lib:
                        lib_objs.append(compute.Library(jar=lib['jar']))
                    elif 'egg' in lib:
                        lib_objs.append(compute.Library(egg=lib['egg']))
                    elif 'whl' in lib:
                        lib_objs.append(compute.Library(whl=lib['whl']))
                if lib_objs:
                    kwargs['libraries'] = lib_objs

            # If task is serverless (no cluster) and no explicit environment_key, default to first env
            if 'existing_cluster_id' not in kwargs and 'environment_key' not in kwargs and default_env_key:
                kwargs['environment_key'] = default_env_key

            task_obj = jobs.Task(**kwargs)
            tasks.append(task_obj)

        return tasks

    def _create_job_progress_notification(self, job_name: str, run_id: int) -> str:
        """Create a progress notification for job execution."""
        from src.models.notifications import Notification, NotificationType
        
        notification = Notification(
            id=f"job-progress-{run_id}-{int(time.time())}",
            type=NotificationType.JOB_PROGRESS,
            title=f"Job Running: {job_name}",
            message=f"Job '{job_name}' (Run ID: {run_id}) is currently running...",
            data={
                "job_name": job_name,
                "run_id": run_id,
                "progress": 0,
                "status": "RUNNING"
            },
            target_roles=["Admin"],  # Only notify admins
            created_at=datetime.utcnow()
        )
        
        # Create notification via notifications manager
        self._notifications_manager.create_notification(notification, db=self._db)
        return notification.id

    def _monitor_job_progress(self, run_id: int, job_name: str, notification_id: str):
        """Monitor job progress and update notification."""
        try:
            while True:
                try:
                    run = self._client.jobs.get_run(run_id=run_id)
                    state = run.state
                    
                    if not state:
                        time.sleep(5)
                        continue
                    
                    # Update notification based on job state
                    if state.life_cycle_state in [RunLifeCycleState.RUNNING, RunLifeCycleState.PENDING]:
                        # Job is still running, update progress
                        progress_data = {
                            "job_name": job_name,
                            "run_id": run_id,
                            "progress": 50 if state.life_cycle_state == RunLifeCycleState.RUNNING else 25,
                            "status": state.life_cycle_state.value
                        }
                        
                        self._update_job_notification(
                            notification_id,
                            f"Job Running: {job_name}",
                            f"Job '{job_name}' (Run ID: {run_id}) is {state.life_cycle_state.value.lower()}...",
                            progress_data
                        )
                        
                        time.sleep(10)  # Check every 10 seconds
                        
                    elif state.life_cycle_state in [RunLifeCycleState.TERMINATED, RunLifeCycleState.SKIPPED, RunLifeCycleState.INTERNAL_ERROR]:
                        # Job completed, update final notification
                        is_success = (
                            state.life_cycle_state == RunLifeCycleState.TERMINATED and 
                            state.result_state == RunResultState.SUCCESS
                        )
                        
                        final_data = {
                            "job_name": job_name,
                            "run_id": run_id,
                            "progress": 100,
                            "status": "SUCCESS" if is_success else "FAILED",
                            "result_state": state.result_state.value if state.result_state else None
                        }
                        
                        title = f"Job {'Completed' if is_success else 'Failed'}: {job_name}"
                        message = f"Job '{job_name}' (Run ID: {run_id}) has {'completed successfully' if is_success else 'failed'}."
                        
                        self._update_job_notification(notification_id, title, message, final_data)
                        
                        # Remove from running jobs tracking
                        self._running_jobs.pop(run_id, None)
                        break
                        
                except Exception as e:
                    logger.error(f"Error monitoring job {run_id}: {e}")
                    time.sleep(30)  # Wait longer on error
                    
        except Exception as e:
            logger.error(f"Failed to monitor job {run_id}: {e}")
            # Clean up on error
            self._running_jobs.pop(run_id, None)

    def _update_job_notification(self, notification_id: str, title: str, message: str, data: Dict[str, Any]):
        """Update an existing job progress notification."""
        try:
            from src.models.notifications import NotificationUpdate
            
            update = NotificationUpdate(
                title=title,
                message=message,
                data=data,
                updated_at=datetime.utcnow()
            )
            
            self._notifications_manager.update_notification(notification_id, update, db=self._db)
            
        except Exception as e:
            logger.error(f"Failed to update notification {notification_id}: {e}")

    def get_job_status(self, run_id: int) -> Optional[Dict[str, Any]]:
        """Get the current status of a running job."""
        try:
            run = self._client.jobs.get_run(run_id=run_id)
            if not run.state:
                return None

            return {
                "run_id": run_id,
                "job_id": run.job_id,
                "life_cycle_state": run.state.life_cycle_state.value,
                "result_state": run.state.result_state.value if run.state.result_state else None,
                "start_time": run.start_time,
                "end_time": run.end_time
            }
        except Exception as e:
            logger.error(f"Failed to get job status for run {run_id}: {e}")
            return None

    def cancel_run(self, run_id: int) -> None:
        """Cancel a running job.

        Args:
            run_id: ID of the job run to cancel

        Raises:
            Exception: If cancellation fails
        """
        try:
            self._client.jobs.cancel_run(run_id=run_id)
            logger.info(f"Cancelled run {run_id}")
        except Exception as e:
            logger.error(f"Error cancelling run {run_id}: {e}")
            raise

    # --- Workflow/job helpers for status and scheduling controls ---
    def get_active_run_id(self, job_id: int) -> Optional[int]:
        """Return the latest active (RUNNING or PENDING) run id for a job if any."""
        try:
            runs = self._client.jobs.list_runs(job_id=job_id, active_only=True)
            for run in runs:
                try:
                    if run.state and run.state.life_cycle_state in [
                        RunLifeCycleState.RUNNING,
                        RunLifeCycleState.PENDING,
                    ]:
                        return int(run.run_id)
                except Exception:
                    continue
            return None
        except Exception as e:
            logger.error(f"Failed to list active runs for job {job_id}: {e}")
            return None

    def pause_job(self, job_id: int) -> None:
        """Pause a scheduled/continuous job by setting pause_status to PAUSED."""
        try:
            job = self._client.jobs.get(job_id=job_id)
            settings = job.settings
            if not settings:
                raise RuntimeError("Job has no settings; cannot pause")

            # Determine if schedule or continuous is configured
            if settings.schedule is not None:
                new_settings = jobs.JobSettings(schedule=jobs.CronSchedule(
                    quartz_cron_expression=settings.schedule.quartz_cron_expression,
                    timezone_id=settings.schedule.timezone_id or 'UTC',
                    pause_status=jobs.PauseStatus.PAUSED,
                ))
                self._client.jobs.update(job_id=job_id, new_settings=new_settings)
                return
            if getattr(settings, 'continuous', None) is not None:
                new_settings = jobs.JobSettings(continuous=jobs.Continuous(
                    pause_status=jobs.PauseStatus.PAUSED
                ))
                self._client.jobs.update(job_id=job_id, new_settings=new_settings)
                return
            raise RuntimeError("Job is not scheduled or continuous; pause unsupported")
        except Exception as e:
            logger.error(f"Failed to pause job {job_id}: {e}")
            raise

    def resume_job(self, job_id: int) -> None:
        """Resume a scheduled/continuous job by setting pause_status to UNPAUSED."""
        try:
            job = self._client.jobs.get(job_id=job_id)
            settings = job.settings
            if not settings:
                raise RuntimeError("Job has no settings; cannot resume")

            if settings.schedule is not None:
                new_settings = jobs.JobSettings(schedule=jobs.CronSchedule(
                    quartz_cron_expression=settings.schedule.quartz_cron_expression,
                    timezone_id=settings.schedule.timezone_id or 'UTC',
                    pause_status=jobs.PauseStatus.UNPAUSED,
                ))
                self._client.jobs.update(job_id=job_id, new_settings=new_settings)
                return
            if getattr(settings, 'continuous', None) is not None:
                new_settings = jobs.JobSettings(continuous=jobs.Continuous(
                    pause_status=jobs.PauseStatus.UNPAUSED
                ))
                self._client.jobs.update(job_id=job_id, new_settings=new_settings)
                return
            raise RuntimeError("Job is not scheduled or continuous; resume unsupported")
        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            raise

    def get_workflow_statuses(self, workflow_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Aggregate statuses for installed workflows.

        Returns dict keyed by workflow_id with fields:
          installed, job_id, is_running, current_run_id, last_result, last_ended_at,
          pause_status (PAUSED|UNPAUSED|NONE), supports_pause
        """
        result: Dict[str, Any] = {}
        try:
            installations = workflow_installation_repo.get_all_installed(self._db)
            for inst in installations:
                if workflow_ids and inst.workflow_id not in workflow_ids:
                    continue
                status: Dict[str, Any] = {
                    'workflow_id': inst.workflow_id,
                    'installed': True,
                    'job_id': int(inst.job_id),
                    'is_running': False,
                    'current_run_id': None,
                    'last_result': None,
                    'last_ended_at': None,
                    'pause_status': 'NONE',
                    'supports_pause': False,
                }

                # Active run
                active_run_id = self.get_active_run_id(inst.job_id)
                if active_run_id:
                    status['is_running'] = True
                    status['current_run_id'] = active_run_id

                # Last run from DB cache if available
                try:
                    last_runs = workflow_job_run_repo.get_recent_runs(self._db, workflow_id=inst.workflow_id, limit=1)
                    if last_runs:
                        last = last_runs[0]
                        status['last_result'] = (last.result_state or '').upper() or None
                        status['last_ended_at'] = last.end_time
                except Exception:
                    pass

                # Pause state / supports_pause
                try:
                    job = self._client.jobs.get(job_id=inst.job_id)
                    settings = job.settings
                    if settings:
                        if settings.schedule is not None:
                            status['supports_pause'] = True
                            status['pause_status'] = (settings.schedule.pause_status.value if settings.schedule.pause_status else 'UNPAUSED')
                        elif getattr(settings, 'continuous', None) is not None:
                            status['supports_pause'] = True
                            cont = settings.continuous
                            status['pause_status'] = (cont.pause_status.value if cont and cont.pause_status else 'UNPAUSED')
                except Exception as e:
                    logger.debug(f"Failed to fetch pause status for job {inst.job_id}: {e}")

                result[inst.workflow_id] = status

            return result
        except Exception as e:
            logger.error(f"Failed to build workflow statuses: {e}")
            return result

    def start_background_polling(self, interval_seconds: int = 300):
        """Start background polling of installed job states.

        Args:
            interval_seconds: Polling interval (default: 5 minutes)
        """
        if self._polling_thread and self._polling_thread.is_alive():
            logger.warning("Background polling already running")
            return

        self._stop_polling.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_job_states,
            args=(interval_seconds,),
            daemon=True,
            name="JobsManagerPoller"
        )
        self._polling_thread.start()
        logger.info(f"Started background job polling (interval: {interval_seconds}s)")

    def stop_background_polling(self):
        """Stop background polling."""
        if not self._polling_thread or not self._polling_thread.is_alive():
            logger.warning("Background polling not running")
            return

        self._stop_polling.set()
        self._polling_thread.join(timeout=10)
        logger.info("Stopped background job polling")

    def _poll_job_states(self, interval_seconds: int):
        """Background task to poll all installed jobs."""
        from src.common.database import get_db

        logger.info("Job state polling thread started")

        while not self._stop_polling.is_set():
            # Create a new database session for this polling iteration
            db = next(get_db())
            try:
                # Get all installed workflows from database
                installations = workflow_installation_repo.get_all_installed(db)
                logger.info(f"Polling {len(installations)} installed workflows...")

                for installation in installations:
                    if self._stop_polling.is_set():
                        break

                    try:
                        # If the Databricks job was deleted, remove the stale installation record
                        try:
                            self._client.jobs.get(job_id=installation.job_id)
                        except Exception as e:
                            try:
                                logger.warning(f"Job {installation.job_id} for workflow {installation.workflow_id} no longer exists. Cleaning up installation record.")
                                workflow_installation_repo.remove(db, id=installation.id)
                                db.commit()
                            except Exception as db_e:
                                logger.error(f"Failed to remove stale installation for workflow {installation.workflow_id}: {db_e}")
                                db.rollback()
                            # Skip further processing for this installation in this cycle
                            continue

                        # Calculate time range for backfill (default: last 7 days)
                        backfill_days = self._settings.JOB_POLLING_BACKFILL_DAYS if self._settings else 7
                        start_time_from = int((datetime.utcnow() - timedelta(days=backfill_days)).timestamp() * 1000)

                        # Get runs from last N days (time range naturally limits results)
                        # This enables backfilling missed runs after app restart/downtime
                        runs = self._client.jobs.list_runs(
                            job_id=installation.job_id,
                            start_time_from=start_time_from
                        )
                        if not runs:
                            continue

                        # Process each run
                        for run in runs:
                            if not run or not run.state:
                                continue

                            # Build run data dict
                            run_data = {
                                'run_name': run.run_name,
                                'life_cycle_state': run.state.life_cycle_state.value if run.state.life_cycle_state else None,
                                'result_state': run.state.result_state.value if run.state.result_state else None,
                                'state_message': run.state.state_message if run.state else None,
                                'start_time': run.start_time,
                                'end_time': run.end_time
                            }

                            # Upsert job run record (creates or updates)
                            job_run = workflow_job_run_repo.upsert_run(
                                db,
                                run_id=run.run_id,
                                workflow_installation_id=installation.id,
                                run_data=run_data
                            )

                            # Create notification if job terminated unsuccessfully (failed, canceled, timed out, etc.)
                            if (run.state.life_cycle_state == RunLifeCycleState.TERMINATED and
                                run.state.result_state != RunResultState.SUCCESS):

                                # Check if we've already notified about this failure
                                if not job_run.notified_at:
                                    logger.info(f"Job {installation.workflow_id} (run {run.run_id}) failed, creating notification")
                                    try:
                                        self._create_job_failure_notification(
                                            installation.name,
                                            installation.workflow_id,
                                            run.run_id,
                                            db
                                        )
                                        # Mark this run as notified only after notification succeeds
                                        workflow_job_run_repo.mark_as_notified(db, run_id=run.run_id)
                                    except Exception as e:
                                        logger.error(f"Failed to create notification for run {run.run_id}: {e}")
                                        # Don't mark as notified so we can retry on next poll
                                else:
                                    logger.debug(f"Already notified about failure of run {run.run_id}, skipping")

                            # Fire success trigger for successfully completed jobs
                            elif (run.state.life_cycle_state == RunLifeCycleState.TERMINATED and
                                  run.state.result_state == RunResultState.SUCCESS):

                                # Check if we've already notified about this success
                                if not job_run.notified_at:
                                    logger.info(f"Job {installation.workflow_id} (run {run.run_id}) succeeded, firing trigger")
                                    try:
                                        self._create_job_success_notification(
                                            installation.name,
                                            installation.workflow_id,
                                            run.run_id,
                                            db
                                        )
                                        # Mark this run as notified only after trigger fires
                                        workflow_job_run_repo.mark_as_notified(db, run_id=run.run_id)
                                    except Exception as e:
                                        logger.error(f"Failed to fire success trigger for run {run.run_id}: {e}")
                                else:
                                    logger.debug(f"Already notified about success of run {run.run_id}, skipping")

                        # Update last polled timestamp on installation (use latest run if available)
                        latest_run = next(iter(runs), None)
                        if latest_run and latest_run.state:
                            latest_run_data = {
                                'run_id': latest_run.run_id,
                                'life_cycle_state': latest_run.state.life_cycle_state.value if latest_run.state.life_cycle_state else None,
                                'result_state': latest_run.state.result_state.value if latest_run.state.result_state else None,
                                'start_time': latest_run.start_time,
                                'end_time': latest_run.end_time
                            }
                            workflow_installation_repo.update_last_polled(
                                db,
                                workflow_id=installation.workflow_id,
                                job_state=latest_run_data
                            )

                    except Exception as e:
                        logger.error(f"Error polling job {installation.job_id} ({installation.workflow_id}): {e}")

                # Commit all updates
                try:
                    db.commit()
                except Exception as e:
                    logger.error(f"Error committing polling updates: {e}")
                    db.rollback()

            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
            finally:
                # Always close the session
                db.close()

            # Wait for next interval or stop signal (unless stopping)
            if not self._stop_polling.is_set():
                self._stop_polling.wait(timeout=interval_seconds)

        logger.info("Job state polling thread stopped")

    def _create_job_failure_notification(self, job_name: str, workflow_id: str, run_id: int, db: Session):
        """Create a notification for job failure using workflow triggers."""
        try:
            from src.common.workflow_triggers import get_trigger_registry
            
            trigger_registry = get_trigger_registry(db)
            entity_data = {
                "workflow_id": workflow_id,
                "job_name": job_name,
                "run_id": run_id,
                "error_type": "job_failure",
            }
            
            executions = trigger_registry.on_job_failure(
                entity_id=str(run_id),
                entity_name=job_name,
                entity_data=entity_data,
                blocking=False,  # Don't block on notifications
            )
            
            if executions:
                logger.info(f"Triggered {len(executions)} workflow(s) for job failure (run {run_id})")
                return
        except Exception as workflow_err:
            logger.error(f"Failed to trigger workflow for job failure: {workflow_err}", exc_info=True)

        # Fallback to direct notification if no workflow configured
        if not self._notifications_manager:
            return

        try:
            from src.models.notifications import Notification, NotificationType

            notification = Notification(
                id=f"job-failure-{workflow_id}-{run_id}-{int(time.time())}",
                type=NotificationType.ERROR,
                title=f"Background Job Failed: {job_name}",
                message=f"Workflow '{job_name}' (ID: {workflow_id}) failed during scheduled execution. Run ID: {run_id}",
                data={
                    "workflow_id": workflow_id,
                    "job_name": job_name,
                    "run_id": run_id,
                    "error_type": "job_failure"
                },
                target_roles=["Admin"],
                created_at=datetime.utcnow()
            )

            self._notifications_manager.create_notification(notification, db=db)
            logger.info(f"No workflow configured; sent direct failure notification for run {run_id}")

        except Exception as e:
            logger.error(f"Failed to create failure notification for workflow '{workflow_id}': {e}")

    def _create_job_success_notification(self, job_name: str, workflow_id: str, run_id: int, db: Session):
        """Create a notification for job success using workflow triggers."""
        try:
            from src.common.workflow_triggers import get_trigger_registry
            
            trigger_registry = get_trigger_registry(db)
            entity_data = {
                "workflow_id": workflow_id,
                "job_name": job_name,
                "run_id": run_id,
            }
            
            executions = trigger_registry.on_job_success(
                entity_id=str(run_id),
                entity_name=job_name,
                entity_data=entity_data,
                blocking=False,  # Don't block on notifications
            )
            
            if executions:
                logger.info(f"Triggered {len(executions)} workflow(s) for job success (run {run_id})")
        except Exception as e:
            logger.error(f"Failed to trigger workflow for job success: {e}", exc_info=True)

