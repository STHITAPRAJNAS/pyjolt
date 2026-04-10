# Copyright 2024 Sthitaprajna Sahoo
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Abstract base class for all transforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Transform(ABC):
    """Abstract base for all JOLT-style transforms."""

    @abstractmethod
    def apply(self, input_data: Any) -> Any:
        """Apply this transform to *input_data* and return the result.

        Parameters
        ----------
        input_data:
            The JSON-compatible Python object to transform.

        Returns
        -------
        Any
            A new JSON-compatible Python object (the transform never mutates
            its input).
        """
