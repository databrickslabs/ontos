"""
Database models for process workflows.

Stores workflow definitions, steps, and execution history for the visual workflow designer.
These are different from Databricks job workflows - these are internal process automation workflows.
"""

import uuid
from sqlalchemy import Column, String, Text, Boolean, Integer, ForeignKey, func, TIMESTAMP, Float
from sqlalchemy.orm import relationship

from src.common.database import Base


class ProcessWorkflowDb(Base):
    """Store process workflow definitions."""
    __tablename__ = 'process_workflows'

    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Basic metadata
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    # Trigger configuration (JSON)
    # Contains: type (on_create, on_update, on_delete, on_status_change, scheduled, manual)
    #           entity_types (list), from_status, to_status, schedule, etc.
    trigger_config = Column(Text, nullable=False)
    
    # Scope configuration (JSON)
    # Contains: type (all, project, catalog, domain), ids (list of scoped entity ids)
    scope_config = Column(Text, nullable=True)
    
    # Workflow type: process (event-driven automation) | approval (wizard-driven agreement/signing)
    workflow_type = Column(String(50), nullable=False, default='process', server_default='process')
    
    # Status
    is_active = Column(Boolean, nullable=False, default=True)
    is_default = Column(Boolean, nullable=False, default=False)
    
    # Version for optimistic locking
    version = Column(Integer, nullable=False, default=1)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)

    # Relationships
    steps = relationship("WorkflowStepDb", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowStepDb.order")
    executions = relationship("WorkflowExecutionDb", back_populates="workflow", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<ProcessWorkflowDb(id='{self.id}', name='{self.name}', is_active={self.is_active})>"


class WorkflowStepDb(Base):
    """Store individual steps within a workflow."""
    __tablename__ = 'workflow_steps'

    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign key to workflow
    workflow_id = Column(String, ForeignKey('process_workflows.id', ondelete='CASCADE'), nullable=False, index=True)

    # Step identifier within workflow (human-readable slug)
    step_id = Column(String(100), nullable=False)

    # Step metadata
    name = Column(String(255), nullable=True)
    
    # Step type: validation, approval, notification, assign_tag, conditional, script, pass, fail, 
    #            policy_check, delivery, create_asset_review, webhook
    step_type = Column(String(50), nullable=False)
    
    # Step configuration (JSON) - type-specific settings
    # For validation: { rule: "DSL rule string" }
    # For approval: { approvers: "domain_owners", timeout_days: 7 }
    # For notification: { recipients: "requester", template: "validation_failed" }
    # For assign_tag: { key: "owner", value: "...", value_source: "current_user" }
    # For conditional: { condition: "DSL expression" }
    # For script: { language: "python", code: "..." }
    # For webhook: { connection_name: "...", url: "...", method: "POST", body_template: "..." }
    config = Column(Text, nullable=True)
    
    # Branching - which step to go to on pass/fail
    # Use step_id values, or null for terminal
    on_pass = Column(String(100), nullable=True)
    on_fail = Column(String(100), nullable=True)
    
    # Order for display/default execution
    order = Column(Integer, nullable=False, default=0)
    
    # Position for visual designer (JSON: {x, y})
    position = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    workflow = relationship("ProcessWorkflowDb", back_populates="steps")
    # A step's results outlive it (ON DELETE SET NULL): they keep step_key and
    # step_name, so an execution still shows a step that was later removed.
    step_executions = relationship("WorkflowStepExecutionDb", back_populates="step", passive_deletes=True)

    def __repr__(self):
        return f"<WorkflowStepDb(id='{self.id}', step_id='{self.step_id}', type='{self.step_type}')>"


class WorkflowExecutionDb(Base):
    """Store workflow execution history."""
    __tablename__ = 'workflow_executions'

    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign key to workflow
    workflow_id = Column(String, ForeignKey('process_workflows.id', ondelete='CASCADE'), nullable=False, index=True)

    # Trigger context (JSON) - what triggered this execution
    # Contains: entity_type, entity_id, trigger_type, user, etc.
    trigger_context = Column(Text, nullable=True)
    
    # Execution status: pending, running, paused, succeeded, failed, cancelled
    status = Column(String(50), nullable=False, default='pending')
    
    # Current step (for paused workflows awaiting approval)
    current_step_id = Column(String(100), nullable=True)
    
    # Result summary
    success_count = Column(Integer, nullable=False, default=0)
    failure_count = Column(Integer, nullable=False, default=0)
    
    # Error message if failed
    error_message = Column(Text, nullable=True)

    # Timestamps
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    
    # Who triggered it
    triggered_by = Column(String(255), nullable=True)

    # Relationships
    workflow = relationship("ProcessWorkflowDb", back_populates="executions")
    step_executions = relationship("WorkflowStepExecutionDb", back_populates="execution", cascade="all, delete-orphan", order_by="WorkflowStepExecutionDb.started_at")

    def __repr__(self):
        return f"<WorkflowExecutionDb(id='{self.id}', workflow_id='{self.workflow_id}', status='{self.status}')>"


class WorkflowStepExecutionDb(Base):
    """Store per-step execution results."""
    __tablename__ = 'workflow_step_executions'

    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))

    # Foreign keys
    execution_id = Column(String, ForeignKey('workflow_executions.id', ondelete='CASCADE'), nullable=False, index=True)
    # The step's row id; null once the step is removed from the workflow
    step_id = Column(String, ForeignKey('workflow_steps.id', ondelete='SET NULL'), nullable=True, index=True)
    # The step's step_id and name when it ran, kept if the step is removed
    step_key = Column(String(100), nullable=True)
    step_name = Column(String(255), nullable=True)

    # Execution status: pending, running, succeeded, failed, skipped
    status = Column(String(50), nullable=False, default='pending')
    
    # Result: passed or failed (for conditional routing)
    passed = Column(Boolean, nullable=True)
    
    # Output/result data (JSON)
    result_data = Column(Text, nullable=True)
    
    # Error message if failed
    error_message = Column(Text, nullable=True)
    
    # Duration in milliseconds
    duration_ms = Column(Float, nullable=True)

    # Timestamps
    started_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)

    # Relationships
    execution = relationship("WorkflowExecutionDb", back_populates="step_executions")
    step = relationship("WorkflowStepDb", back_populates="step_executions")

    def __repr__(self):
        return f"<WorkflowStepExecutionDb(id='{self.id}', step_id='{self.step_id}', status='{self.status}')>"

