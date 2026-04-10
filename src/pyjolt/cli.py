# Copyright 2024 Sthitaprajna Sahoo and contributors
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

"""Command line interface for pyjolt."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .chainr import Chainr
from .exceptions import PyJoltError
from .transforms import Shift


def main() -> None:
    """Run the pyjolt CLI."""
    parser = argparse.ArgumentParser(
        description="High-performance Python implementation of the JOLT JSON transformation library."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=argparse.FileType("r"),
        default=sys.stdin,
        help="Input JSON file (default: stdin)",
    )
    parser.add_argument(
        "-s", "--spec", required=True, type=argparse.FileType("r"), help="JOLT spec JSON file"
    )
    parser.add_argument(
        "-o",
        "--output",
        type=argparse.FileType("w"),
        default=sys.stdout,
        help="Output JSON file (default: stdout)",
    )
    parser.add_argument(
        "-i", "--indent", type=int, help="Number of spaces for JSON indentation", default=None
    )

    args = parser.parse_args()

    try:
        # Load input and spec
        input_data = json.load(args.input)
        spec_data = json.load(args.spec)

        # Decide whether to use Chainr (if list) or Shift (if dict)
        if isinstance(spec_data, list):
            transform = Chainr.from_spec(spec_data)
        elif isinstance(spec_data, dict):
            transform = Shift(spec_data)
        else:
            print(
                "Error: Spec must be a list (for Chainr) or a dict (for Shift).", file=sys.stderr
            )
            sys.exit(1)

        # Apply transformation
        result = transform.apply(input_data)

        # Output result
        json.dump(result, args.output, indent=args.indent)
        args.output.write("\n")

    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON - {e}", file=sys.stderr)
        sys.exit(1)
    except PyJoltError as e:
        print(f"Error: Transformation failed - {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: An unexpected error occurred - {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
