"""Pydantic input models for SDLC Assist MCP tools."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ArtifactType(str, Enum):
    """Valid artifact types that can be retrieved from a project."""

    PRD = "prd"
    DESIGN_SYSTEM = "design_system"
    ARCHITECTURE = "architecture"
    DATA_MODEL = "data_model"
    API_CONTRACT = "api_contract"
    SEQUENCE_DIAGRAMS = "sequence_diagrams"
    IMPLEMENTATION_PLAN = "implementation_plan"
    CLAUDE_MD = "claude_md"
    CORPORATE_GUIDELINES = "corporate_guidelines"


# Maps ArtifactType enum values to the actual database column names
ARTIFACT_COLUMN_MAP: dict[str, str] = {
    ArtifactType.PRD: "prd_content",
    ArtifactType.DESIGN_SYSTEM: "design_system_content",
    ArtifactType.ARCHITECTURE: "arch_overview_content",
    ArtifactType.DATA_MODEL: "data_model_content",
    ArtifactType.API_CONTRACT: "api_contract_content",
    ArtifactType.SEQUENCE_DIAGRAMS: "sequence_diagrams_content",
    ArtifactType.IMPLEMENTATION_PLAN: "implementation_plan_content",
    ArtifactType.CLAUDE_MD: "claude_md_content",
    ArtifactType.CORPORATE_GUIDELINES: "corporate_guidelines_content",
}


class ListProjectsInput(BaseModel):
    """Input for listing all SDLC projects."""

    model_config = ConfigDict(str_strip_whitespace=True)

    status_filter: Optional[str] = Field(
        default=None,
        description=(
            "Filter projects by status. "
            "Valid values: 'DRAFT', 'ACTIVE', 'COMPLETED', 'ARCHIVED'. "
            "Omit to return all projects."
        ),
    )


class GetProjectSummaryInput(BaseModel):
    """Input for getting a detailed project summary."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(
        ...,
        description=(
            "UUID of the project to retrieve. "
            "Get this from the sdlc_list_projects tool."
        ),
        min_length=1,
    )


class GetArtifactInput(BaseModel):
    """Input for fetching a specific artifact from a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(
        ...,
        description=(
            "UUID of the project. "
            "Get this from the sdlc_list_projects tool."
        ),
        min_length=1,
    )
    artifact_type: ArtifactType = Field(
        ...,
        description=(
            "The type of artifact to retrieve. Valid values: "
            "'prd', 'design_system', 'architecture', 'data_model', "
            "'api_contract', 'sequence_diagrams', 'implementation_plan', "
            "'claude_md', 'corporate_guidelines'"
        ),
    )


class GetScreensInput(BaseModel):
    """Input for listing screens belonging to a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(
        ...,
        description=(
            "UUID of the project. "
            "Get this from the sdlc_list_projects tool."
        ),
        min_length=1,
    )
    include_prototypes: bool = Field(
        default=False,
        description=(
            "If true, include the full HTML prototype content for each screen. "
            "This can be very large — only set to true if you need the actual HTML."
        ),
    )


class GetTechPreferencesInput(BaseModel):
    """Input for fetching tech stack preferences for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(
        ...,
        description=(
            "UUID of the project. "
            "Get this from the sdlc_list_projects tool."
        ),
        min_length=1,
    )

class GenerateEstimationInput(BaseModel):
    """Input for generating IT cost estimates."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: str = Field(
        ...,
        description=(
            "UUID of the project to estimate. "
            "Requires all upstream artifacts (PRD, architecture, data model, "
            "API contract, implementation plan) to be generated first."
        ),
        min_length=1,
    )