# ComfyUI Workflow

`haybale-comfyui:node:ComfyUIWorkflowNode` · kind: node

Runs a workflow on a ComfyUI server and returns its images

## Ports

| id | direction | type | description |
|---|---|---|---|
| `source.workflow` | config | `haywire-core:type:CHOICES` | A workflow open in ComfyUI that holds a Haywire Output, by its file name. Picking one rebuilds the node's inlets and outlets from its Haywire nodes |
| `source.reload` | config | `haywire-core:type:BOOL` | Take the workflow's latest version from ComfyUI |
| `progress.main` | config | `haywire-core:type:PROGRESS` |  |
| `out_image` | outlet | `haybale-image:type:IMAGE` | Haywire Output 'Image' |

## Settings

| name | bag | default | description |
|---|---|---|---|
| `workflow` | source | `''` | A workflow open in ComfyUI that holds a Haywire Output, by its file name. Picking one rebuilds the node's inlets and outlets from its Haywire nodes |
| `reload` | source | `False` | Take the workflow's latest version from ComfyUI |
| `main` | progress | `PROGRESS(active=False, fraction=None, label='')` |  |

## Notes

Runs a workflow on a ComfyUI server and returns its images.

Build the workflow in ComfyUI (server address: *ComfyUI* library settings) with the
comfyui-haywire nodes installed, and mark what haywire controls:

- *Haywire Parameter* becomes an inlet (number, integer, toggle, text, prompt, choice).
- *Haywire Image* becomes an IMAGE inlet.
- *Haywire Output* becomes an IMAGE outlet.

While the workflow is open in ComfyUI it appears under `Workflow` by its file name.
Picking it copies it into this node, so the graph runs later without ComfyUI's page
open. When the workflow changes in ComfyUI the card says so; press `Reload` to take
the new version.

The node runs again when an inlet changes. To get a new image from the same inputs,
expose the seed as a Haywire Parameter and change it.
