"""Shared path policy for authored agent instructions, never agent settings.

This only identifies conventional instruction locations. It neither reads nor
executes their contents; discovery and harvest retain their existing budgets.
"""
from pathlib import PurePosixPath


HIDDEN_INSTRUCTIONS = {
    '.claude': frozenset({'commands', 'agents', 'skills'}),
    '.agents': frozenset({'skills'}),
    '.codex': frozenset({'prompts', 'skills'}),
}
INSTRUCTION_DIRS = frozenset({'commands', 'agents', 'skills', 'prompts'})
INSTRUCTION_NAMES = frozenset({'claude.md', 'agents.md', 'skill.md'})
PRIVATE_PARTS = frozenset({'secrets', 'credentials', 'generated', '__generated__'})


def instruction_document(relative):
    """Markdown instructions in native locations or visible exported folders."""
    path = PurePosixPath(relative)
    if path.suffix.casefold() != '.md':
        return False
    return path.name.casefold() in INSTRUCTION_NAMES or any(
        part.casefold() in INSTRUCTION_DIRS or
        any(part.casefold().endswith('-' + kind) for kind in INSTRUCTION_DIRS)
        for part in path.parts[:-1])


def permitted_path(relative, *, directory=False):
    """Permit ordinary paths and only narrow hidden instruction subtrees.

    Hidden namespace directories are traversable solely to reach their known
    instruction folders. Hidden files and other hidden components stay excluded.
    """
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or any(part.casefold() in PRIVATE_PARTS for part in path.parts):
        return False
    hidden = False
    for index, part in enumerate(path.parts):
        if not part.startswith('.'):
            continue
        hidden = True
        children = HIDDEN_INSTRUCTIONS.get(part)
        if children is None:
            return False
        if index + 1 == len(path.parts):
            return directory
        if path.parts[index + 1] not in children:
            return False
    return not hidden or directory or instruction_document(path)
