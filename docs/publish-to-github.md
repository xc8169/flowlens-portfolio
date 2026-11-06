# Publish this source repository

The local repository is prepared for review; no remote has been created or pushed automatically. Choose the GitHub account, visibility and license before publishing. The included MIT license is the proposed license for original project code. A private repository can be shared with a reviewer; a public one is readable by anyone.

## GitHub Desktop route

1. Open GitHub Desktop and choose File → Add local repository. Select this folder. If using the source ZIP, extract it first and create a repository from the extracted folder when prompted.
2. Review changed files. The expected content is source, docs, tests, icon assets and small generated viewer data. Installed runtimes, build outputs, recordings and research model weights are ignored.
3. Create the first commit using your own configured Git identity. A suitable message is `Prepare FlowLens scientific software portfolio`.
4. Choose Publish repository, repository name `flowlens`, your account and desired visibility.
5. Check the repository's Actions tab after the push. The configured remote workflows have not run until a push occurs. Copy the repository URL to share with the reviewer.

## Git CLI route

In this repository, after configuring your own Git name and GitHub-associated email:

```sh
git status
git add .
git commit -m "Prepare FlowLens scientific software portfolio"
# Create an empty repository named flowlens in your GitHub account first.
# Replace YOUR_GITHUB_USERNAME below with your actual account name.
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/flowlens.git
git push -u origin main
```

The directory is initialized locally on branch main. No fabricated commit identity, past timestamps or development history is supplied. If Git initialization is unavailable in an extracted ZIP, run `git init -b main` before the commands above.

## Reviewer entry points

The README's browser demo command runs with standard Python only and needs no GPU. The Python validation runner and C# desktop need the setup described in README. Start the code review with scripts/demo.py, engine/torch_interface.py, desktop/WorkerClient.cs, desktop/WorkflowNavigator.cs and web/model.js.

GitHub's official guidance: https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github. Workflow references: https://docs.github.com/en/actions/tutorials/build-and-test-code/python and https://docs.github.com/en/actions/tutorials/build-and-test-code/nodejs.
