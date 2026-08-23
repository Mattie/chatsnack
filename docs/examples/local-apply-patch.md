# Local Apply Patch workspace

Apply Patch asks your Python code to make each file change. `LocalWorkspace` is
a working implementation you can copy when those changes should stay inside one
directory.

[Download `apply_patch_workspace.py`](https://raw.githubusercontent.com/Mattie/chatsnack/master/examples/apply_patch_workspace.py),
then put it beside your application.

```python
from pathlib import Path

from chatsnack import Chat, utensil
from apply_patch_workspace import LocalWorkspace

workspace = LocalWorkspace(Path("my-project"))
patch = utensil.apply_patch(execute=workspace.apply_patch)

editor = Chat(
    "Edit only files inside the project.",
    utensils=[patch],
)

edited = editor.chat("In menu.txt, replace `kettle corn` with `caramel corn`.")
print(edited.last)
```

The directory must already exist. Choosing it is the permission decision: once
the utensil is attached, the chat may create, update, or delete UTF-8 text files
anywhere below that directory.

The example follows the operation-level V4A format described in OpenAI's
[Apply Patch guide](https://developers.openai.com/api/docs/guides/tools-apply-patch).
That contract was checked on August 22, 2026. The code refuses absolute paths,
`..` traversal, symlinks, directory targets, and patches whose context no longer
matches the file. An update is written only after the entire diff parses
successfully.

Each operation finishes independently. If a later operation fails, earlier
changes remain on disk. Add your application's approvals, evidence, backups,
and recovery around `workspace.apply_patch`. For hostile or concurrently
modified workspaces, use an operating-system sandbox as well.
