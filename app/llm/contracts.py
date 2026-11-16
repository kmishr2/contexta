from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.onboarding.metrics import Definition


class DraftProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['proposal', 'clarify', 'unsupported']
    message: str = Field(min_length=1, max_length=500)
    definition: Definition | None = None

    @model_validator(mode='after')
    def shape(self):
        if (self.kind == 'proposal') != (self.definition is not None):
            raise ValueError('Only proposals contain a definition')
        return self


class ChatPlan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['query', 'clarify', 'unsupported']
    message: str = Field(min_length=1, max_length=500)
    metric_id: str | None = Field(default=None, max_length=80)
    period: Literal['explicit', 'last_month'] | None = None
    start: date | None = None
    end: date | None = None
    dimensions: list[str] = Field(default_factory=list, max_length=10)
    filters: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode='after')
    def shape(self):
        if self.kind == 'query':
            if not self.metric_id or not self.period:
                raise ValueError('Query needs a metric and period')
            if self.period == 'explicit' and (not self.start or not self.end or self.start >= self.end):
                raise ValueError('Explicit period needs an ordered date window')
            if self.period == 'last_month' and (self.start or self.end):
                raise ValueError('Relative period cannot include dates')
        elif self.metric_id or self.period or self.start or self.end or self.dimensions or self.filters:
            raise ValueError('Only a query can specify query fields')
        return self
