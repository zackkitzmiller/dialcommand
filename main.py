import os
import sys

from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport

from .actions.DialCommand.DialCommand import DialCommand

sys.path.append(os.path.dirname(__file__))


class DialCommandPlugin(PluginBase):
    def __init__(self):
        self.PLUGIN_NAME = "Dial Command"
        self.GITHUB_REPO = (
            "https://github.com/z19r/streamcontroller-dial-command"
        )
        super().__init__()

        self.lm = self.locale_manager
        self.lm.set_to_os_default()
        self.lm.set_fallback_language("en_US")

        self.dial_command_holder = ActionHolder(
            plugin_base=self,
            action_base=DialCommand,
            action_id_suffix="DialCommand",
            action_name=self.lm.get("actions.dial-command.name"),
            action_support={
                Input.Key: ActionInputSupport.SUPPORTED,
                Input.Dial: ActionInputSupport.SUPPORTED,
                Input.Touchscreen: ActionInputSupport.UNTESTED,
            },
        )
        self.add_action_holder(self.dial_command_holder)

        self.register(
            plugin_name=self.lm.get("plugin.name"),
            github_repo=self.GITHUB_REPO,
            plugin_version="1.0.0",
            app_version="1.5.0-beta",
        )
