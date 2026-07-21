"""
Custom build hook to include the README from the root directory in the build.

The batch force-include option cannot be used because the build directory changes
between editable and non-editable installs.
This hook will attempt to infer the correct path to the README file and include it in the build.
"""

import os
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """
    Custom build hook to include the README from the root directory in the build.
    """

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """
        Initialize the build hook

        Updates the build data to include the README file from the root directory.
        """
        build_data["force_include"][os.path.join(os.environ["PWD"], "README.md")] = "other_data.md"
        print(f"Initializing {version} with {build_data}")
