export interface MaturityGate {
  id: string;
  maturity_level_id: string;
  compliance_policy_id: string;
  compliance_policy_name: string | null;
  compliance_policy_rule: string | null;
  required: boolean;
  display_order: number;
  created_at: string | null;
}

export interface MaturityLevel {
  id: string;
  level_order: number;
  name: string;
  description: string | null;
  icon: string | null;
  color: string | null;
  entity_type: string;
  gates: MaturityGate[];
  created_at: string | null;
  updated_at: string | null;
}

export interface GateResult {
  gate_id: string;
  policy_id: string;
  policy_name: string;
  required: boolean;
  passed: boolean;
  message: string | null;
}

export interface LevelResult {
  level_order: number;
  level_name: string;
  level_icon: string | null;
  level_color: string | null;
  achieved: boolean;
  gates: GateResult[];
}

export interface MaturityReport {
  entity_type: string;
  entity_id: string;
  entity_name: string | null;
  achieved_level_order: number | null;
  achieved_level_name: string | null;
  total_levels: number;
  gates_passed: number;
  gates_total: number;
  levels: LevelResult[];
  evaluated_at: string;
  evaluated_by: string | null;
}

export interface MaturitySnapshot {
  id: string;
  entity_type: string;
  entity_id: string;
  achieved_level_order: number | null;
  achieved_level_name: string | null;
  total_levels: number;
  gates_passed: number;
  gates_total: number;
  gate_results_json: string | null;
  evaluated_at: string;
  evaluated_by: string | null;
}
