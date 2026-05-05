from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModelLifecyclePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    load: Literal["on_demand"] = "on_demand"
    unload: Literal["never", "after_run", "manual"] = "never"
    unload_failure: Literal["ignore", "warn", "fail"] = "warn"

