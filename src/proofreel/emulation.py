"""What a web run changes in its page for one recording.

The recorder holds the change on its own DevTools connection: Chrome undoes it when that connection ends, so a
recorder that stops or dies leaves the page as it was. Each change is a pair of DevTools commands: one that sets it,
one that clears it. The commands are saved in session.json (`emulate`), and the recorder runs them before its first frame, so
`start` returns when they hold.
"""

REDUCED_MOTION = [["Emulation.setEmulatedMedia", {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]}],
                  ["Emulation.setEmulatedMedia", {"features": []}]]


def commands(reduced_motion):
    return [REDUCED_MOTION] if reduced_motion else []
