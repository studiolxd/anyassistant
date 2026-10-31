"""Tap to wake: asleep, a tap on the screen wakes it up (its sound, «Listening»), as
if it had heard its name. Awake, a tap does what it did (stops it talking, silences
an alarm): this only listens to taps while it sleeps.
"""

import events


@events.on("tap")
def wake(jarvis):
    jarvis.ear.wake_up("tap")
