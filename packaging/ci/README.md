# CI recipe: build Windows, macOS and Linux installers from one push

`build.yml` is a ready-to-use GitHub Actions workflow. It is stored here (and
not in `.github/workflows/`) only because the bot that produced this branch is
not allowed to create workflow files. **Install it with one command:**

```bash
mkdir -p .github/workflows
cp packaging/ci/build.yml .github/workflows/build.yml
git add .github/workflows/build.yml
git commit -m "ci: build desktop installers on Windows, macOS and Linux"
git push
```

## What it does

| Job | Runner | Artifacts |
|---|---|---|
| `test` | ubuntu / windows / macos | runs `pytest -q` on all three |
| `build` | `windows-latest` | `TimetableGenerator.exe`, `.zip`, `.msi` |
| `build` | `ubuntu-22.04` | binary, `.tar.gz`, `.deb` |
| `build` | `macos-13` | Intel `.dmg` |
| `build` | `macos-14` | Apple Silicon `.dmg` |
| `release` | on `v*` tags | attaches every artifact to a GitHub Release |

## Using it

```bash
# build now, on any branch
gh workflow run "Build desktop installers" --ref <your-branch>
gh run watch
gh run download                 # every installer, into the current folder

# publish a versioned release with all installers attached
git tag v2.0.0 && git push origin v2.0.0
```

Runners are free for public repositories.
