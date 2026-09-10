"""Errors suitable for student scripts; request failures never silently retry actions."""
class CourseError(RuntimeError):
    pass
class ConnectionError(CourseError):
    pass
class ProtocolError(CourseError):
    pass
class ActionError(CourseError):
    def __init__(self, code, response=None):
        self.code, self.response = code, response or {}
        hints = {
            'control_released': 'Control stopped; the game is watching. Explicitly take_control() to resume.',
            'manual_control_active': 'A human is playing. Press Esc or F8 in the game to return to watching before take_control().',
            'stale_control_epoch': 'Control changed. Observe and explicitly take_control() again.',
            'close_menu_before_acquire': 'Close the in-game menu before handing control to Python.',
            'close_menu_before_input': 'Close the inventory or form before moving.',
            'manual_pause_active': 'A human paused the game; close the pause menu manually.',
            'stale_form': 'The form changed. Observe the current form again before moving items.',
            'player_dead': 'The player is dead. Respawn before continuing.',
            'node_observation_restricted_by_server': 'The server restricts scripted node observations.',
        }
        super().__init__(hints.get(code, code.replace('_', ' ')))
class ActionTimeout(CourseError):
    pass
class ActionCancelled(CourseError):
    pass
