"""Typed Project HTTP responses and merge-time PATCH documentation."""

from typing import Annotated

from pydantic import Field, RootModel

from ai_workbench.api.schemas.common import ApiModel, patch_model, public_model
from ai_workbench.core.schema.project import WorkspaceInput, TimelineInput, WorkspaceProject, TimelineProject
from ai_workbench.core.session import WorkspaceOverrides


WorkspaceProjectResponse = public_model("WorkspaceProjectResponse", WorkspaceProject)
TimelineProjectResponse = public_model("TimelineProjectResponse", TimelineProject)
ProjectResponse = Annotated[WorkspaceProjectResponse | TimelineProjectResponse, Field(discriminator="kind")]
WorkspaceProjectPatch = patch_model("WorkspaceProjectPatch", WorkspaceInput, omit={"kind"})
TimelineProjectPatch = patch_model("TimelineProjectPatch", TimelineInput, omit={"kind"})


class ProjectPatchRequest(RootModel[WorkspaceProjectPatch | TimelineProjectPatch]):
    pass


class ProjectDeleted(ApiModel):
    deleted: bool
    project_id: str
    deleted_session_ids: list[str]


class WorkspaceSessionCreate(ApiModel):
    title: str = Field(default="", max_length=120)
    overrides: WorkspaceOverrides = Field(default_factory=WorkspaceOverrides)
