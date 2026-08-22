"""Shape and scenario contracts consumed by the generic matrix driver."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence


CanonicalTranscript = object


@dataclass(frozen=True, slots=True)
class MatrixCase:
    name: str
    node_options: tuple[str, ...]
    client_options: tuple[str, ...]
    expected: CanonicalTranscript


@dataclass(frozen=True, slots=True)
class MatrixShape:
    name: str
    scenario_names: tuple[str, ...]
    load_case: Callable[[str], MatrixCase]
    canonicalize: Callable[[str], CanonicalTranscript]

    def node_command(self, tool: Sequence[str], case: MatrixCase) -> list[str]:
        return [*tool, "node", "--shape", self.name, *case.node_options]

    def client_command(self, tool: Sequence[str], case: MatrixCase) -> list[str]:
        return [*tool, "client", "--shape", self.name, *case.client_options]


ShapeRegistry = Mapping[str, MatrixShape]
