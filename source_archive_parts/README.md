# Source archive parts

The complete News Studio AI v0.2.0 source package is stored here as nine Base64 text parts because the GitHub file API used for this upload does not directly accept a local binary archive.

From the repository root, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\rebuild_source.ps1
```

This recreates `NewsStudioAI_v0.2.0_Windows_Source.tar.xz` in the repository root. Extract it with 7-Zip or Windows `tar -xf`.

The script checks that all nine parts are present and that the combined payload has the expected length before writing the archive.