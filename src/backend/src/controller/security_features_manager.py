from pathlib import Path
from typing import Dict, List, Optional

import yaml

from src.models.security_features import SecurityFeature

from src.common.logging import get_logger
logger = get_logger(__name__)

class SecurityFeaturesManager:
    def __init__(self):
        self.features: Dict[str, SecurityFeature] = {}

    def create_feature(self, feature: SecurityFeature) -> SecurityFeature:
        self.features[feature.id] = feature
        return feature

    def get_feature(self, feature_id: str) -> Optional[SecurityFeature]:
        feature = self.features.get(feature_id)
        return feature

    def list_features(self) -> List[SecurityFeature]:
        try:
            features = list(self.features.values())
            for feature in features:
                try:
                    # Verify the feature can be converted to dict
                    feature_dict = feature.to_dict()
                except Exception as e:
                    logger.error(f"Error processing feature {feature.id if hasattr(feature, 'id') else 'unknown'}")
                    logger.error(f"Error: {e!s}")
                    import traceback
                    logger.error(f"Stack trace: {traceback.format_exc()}")
                    raise
            return features
        except Exception as e:
            logger.error(f"Error in list_features: {e!s}")
            logger.error(f"Error type: {type(e)}")
            import traceback
            logger.error(f"Stack trace: {traceback.format_exc()}")
            raise

    def update_feature(self, feature_id: str, feature: SecurityFeature) -> Optional[SecurityFeature]:
        if feature_id not in self.features:
            logger.warning(f"Security feature not found: {feature_id}")
            return None
        self.features[feature_id] = feature
        return feature

    def delete_feature(self, feature_id: str) -> bool:
        if feature_id not in self.features:
            logger.warning(f"Security feature not found: {feature_id}")
            return False
        del self.features[feature_id]
        return True

    def load_from_yaml(self, yaml_path: Path) -> bool:
        try:
            if not yaml_path.exists():
                logger.warning(f"YAML file not found at {yaml_path}")
                return False
            
            with open(yaml_path, 'r') as f:
                try:
                    data = yaml.safe_load(f)
                except yaml.YAMLError as e:
                    logger.error(f"Error parsing YAML syntax in {yaml_path}: {e!s}")
                    return False

                if not data:
                    logger.info(f"YAML file at {yaml_path} is empty. No features loaded.")
                    return True # Successfully loaded an empty file

                if 'features' not in data:
                    logger.warning(f"'features' key not found in YAML data at {yaml_path}. No features loaded.")
                    return True # File loaded, but no 'features' section

                features_list = data.get('features')
                if not isinstance(features_list, list):
                    logger.warning(f"'features' key in YAML at {yaml_path} is not a list. Found type: {type(features_list)}. No features loaded.")
                    return False

                if not features_list:
                    logger.info(f"YAML file loaded from {yaml_path}, and the 'features' list was empty. No features loaded.")
                    return True

                loaded_count = 0
                for i, feature_data in enumerate(features_list):
                    try:
                        if not isinstance(feature_data, dict) or 'id' not in feature_data:
                            logger.warning(f"Skipping invalid feature entry #{i+1} (not a dict or no id) in {yaml_path}: {feature_data}")
                            continue
                        feature = SecurityFeature.from_dict(feature_data)
                        self.features[feature.id] = feature
                        loaded_count += 1
                    except Exception as e:
                        logger.error(f"Error processing feature entry #{i+1} from {yaml_path}: {feature_data}. Error: {e!s}")
                        import traceback
                        logger.debug(f"Stack trace for feature error: {traceback.format_exc()}")
                
                if loaded_count > 0:
                    logger.info(f"Successfully loaded {loaded_count} security features out of {len(features_list)} entries from {yaml_path}.")
                elif len(features_list) > 0:
                    logger.warning(f"No security features were successfully loaded from {len(features_list)} entries in {yaml_path} due to errors in all entries.")
                # If features_list was empty and loaded_count is 0, it's covered by "empty list" case returning True.
                
                return True # Indicates the file was processed, even if some/all individual items failed.

        except Exception as e:
            logger.error(f"Unexpected error loading security features from YAML {yaml_path}: {e!s}")
            import traceback
            logger.error(f"Stack trace for unexpected error: {traceback.format_exc()}")
            return False

    def save_to_yaml(self, yaml_path: Path) -> None:
        try:
            data = {'features': [feature.to_dict() for feature in self.features.values()]}
            with open(yaml_path, 'w') as f:
                yaml.dump(data, f)
        except Exception as e:
            logger.exception(f"Error saving security features to YAML: {e!s}")
            raise
