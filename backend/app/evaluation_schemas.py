"""Database-backed evaluation contracts. Provider keys are never accepted or stored."""
import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .providers.registry import resolve_embedding_dimensions, validate_llm


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=4000)
    expected: str = Field(default="", max_length=4000)
    match: Literal["contains", "exact"] = "contains"
    source: str = Field(default="", max_length=500)


class EvaluationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    llm_provider: str = Field(min_length=1, max_length=100)
    llm_model: str = Field(min_length=1, max_length=200)
    embedding_provider: str = Field(min_length=1, max_length=100)
    embedding_model: str = Field(min_length=1, max_length=200)
    embedding_dimensions: int = Field(ge=1, le=8192)
    top_k: int = Field(default=5, ge=1, le=20)
    min_similarity: float = Field(default=0.2, ge=0, le=1)
    min_strong: int = Field(default=1, ge=0, le=20)
    cross_lingual_floor: float | None = Field(default=None, ge=0, le=1)
    answer_language: str | None = Field(default=None, max_length=100)
    answer_language_strict: bool = True
    answer_disclaimer: str | None = Field(default=None, max_length=2000)
    document_language: str | None = Field(default=None, max_length=100)
    hybrid_search: bool = True
    include_memories: bool = True

    @model_validator(mode="after")
    def supported_models(self):
        validate_llm(self.llm_provider, self.llm_model)
        resolve_embedding_dimensions(self.embedding_provider, self.embedding_model, self.embedding_dimensions)
        return self


class EvaluationSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[2] = 2
    cases: list[EvaluationCase] = Field(default_factory=list, max_length=20)
    variants: list[EvaluationConfig] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Question IDs must be unique")
        if "\\u0000" in self.model_dump_json():
            raise ValueError("NUL characters are not supported")
        return self


class SaveEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)
    suite: EvaluationSuite


class StartEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: uuid.UUID
    suite: EvaluationSuite
