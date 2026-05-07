from ai_workbench.core.schema.context_policy import ContextPolicy
from ai_workbench.core.schema.model_lifecycle import ModelLifecyclePolicy


DEFAULT_CONTEXT_POLICY = ContextPolicy(mode="recent_messages", max_messages=8)
DEFAULT_MODEL_LIFECYCLE = ModelLifecyclePolicy(load="on_demand", unload="never", unload_failure="warn")
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_ALLOW_SESSION_OVERRIDE = True

