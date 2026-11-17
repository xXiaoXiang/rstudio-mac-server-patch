# Patched Development Workspace Backup

This branch is a source and configuration backup of the RStudio Server on
macOS VM. It excludes the sibling rstudio-2026.11.0-203 directory, generated
build outputs, downloaded dependencies, and credentials. The main branch stays
dedicated to the patch series and release automation.

Start with [the restore guide](workspace-state/RESTORE.md) to restore the RStudio local Git history
and rebuild the Server package. The original RStudio checkout was shallow, but
its local refs and available objects are preserved in checksummed archive parts.

The Linux portal under R_in_conda/ requires CONDA_R_FLASK_SECRET_KEY before
launch. Its previous signing key is intentionally absent from this backup.
