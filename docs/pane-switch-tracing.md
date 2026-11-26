# Pane Switch Tracing

Measures what happens between a right-rail click and the new pane appearing.

## Turn it on

Set `AIGATOR_PANE_TRACE=1` before starting the shell. Use a separate backend port and Electron profile so your normal sessions are untouched. For screenshots of hidden panes, also pass `--disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding`.

Each rail click prints one line to the shell's stdout:

```
[pane-trace] {"app":"teams","clickToShowIpcMs":9,"clickToLayoutMs":14,"clickToFrameMs":41,"layoutPasses":2,"nullActivePasses":1,"hideIpcs":14,"noopHideIpcs":13}
```

| Field                       | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `clickToShowIpcMs`          | Click in the renderer until the shell receives `external-pane:show`: renderer work plus IPC delivery.                                                                                                                                                                                                                                                                                                                    |
| `clickToLayoutMs`           | Click until the first layout pass.                                                                                                                                                                                                                                                                                                                                                                                       |
| `clickToFrameMs`            | Click until the target view has rendered two animation frames. A proxy for "visible", not exact compositor presentation. Only warm native-to-native switches measure first paint. On a cold open or a same-app re-click the probe waits for the page to finish loading, so the value is the load time, or `null` if that takes longer than 1.5s. Always `null` for panes with no native view, such as Calendar and Code. |
| `layoutPasses`              | Layout passes from the click until the first frame (or 1.5s), from any cause (window resize, toolbar, drawer included). More than 1 on a warm switch means intermediate states were painted.                                                                                                                                                                                                                             |
| `nullActivePasses`          | Passes that ran with no active external app. For a native-to-native switch this is the full-width Gator flash. For Calendar and Code it is expected.                                                                                                                                                                                                                                                                     |
| `hideIpcs` / `noopHideIpcs` | Hide calls received, and how many were ignored because that app was not active.                                                                                                                                                                                                                                                                                                                                          |

## What to look for

- `nullActivePasses` above 0 on a native-to-native switch: hide and show landed in different event-loop turns.
- `clickToFrameMs` over about 100ms: the click-to-visible path is slow. Compare `clickToShowIpcMs` (renderer work plus IPC delivery) with the gap after it (shell and first paint). Only the native-view side is measured; the Gator-side `body.gator-split` reflow is not.
- A large `noopHideIpcs`: confirms most hides do nothing.

## Deeper checks

- Start the shell with `--remote-debugging-port=9223`, open the Gator page in DevTools, and record the Performance panel over ten rail clicks. Look for long tasks right after the click.
- Screen-record at 60 fps or higher and count blank or full-width-Gator frames per switch.
