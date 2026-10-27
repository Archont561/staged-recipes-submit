"""Repository contracts, Python quality gates, and the full local CI task."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from common import ROOT, AutomationError, load_yaml, read_toml, run

REQUIRED_FILES = (
    "action.yml",
    "pyproject.toml",
    "pixi.toml",
    "lefthook.yml",
    "config/actions.lock.json",
    "config/sandbox-bootstrap.json",
    "pixi-sandbox.toml",
    "docs/GUIDE.md",
    "docs/DEVELOPMENT.md",
    "docs/ARCHITECTURE.md",
    ".devcontainer/devcontainer.json",
    ".devcontainer/Dockerfile",
    ".devcontainer/post-create.sh",
    "config/project.toml",
    "README.md",
    "LICENSE",
)
REQUIRED_WORKFLOWS = {"ci.yml", "release.yml"}
PACKAGE = "staged_recipes_submit"
# Written by `pixi-sandbox init`, not by hand. They are allowed to exist, but they must satisfy
# the sandbox policy below as soon as they do.
GENERATED_WORKFLOWS = {"publish-sandbox.yml", "relock.yml"}
SANDBOX_CONFIG = "pixi-sandbox.toml"
SANDBOX_BOOTSTRAP = "config/sandbox-bootstrap.json"
STANDARD_PLATFORMS = {"linux-64", "osx-64", "osx-arm64", "win-64"}
SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_TIMEOUT_MINUTES = 1440
MAX_README_LINES = 80
DISPATCHER = "scripts/run.py"
# The whole Python surface: one package at the root plus automation and tests.
SOURCES = (PACKAGE, "scripts", "tests")
DEVCONTAINER = Path(".devcontainer")
# Provisioning may only reach the task dispatcher: no bespoke install logic in the container.
FORBIDDEN_IN_POST_CREATE = (
    "pip install",
    "curl ",
    "wget ",
    "apt-get",
    "conda install",
    "npm install",
)
MINIMUM_COVERAGE = 90
_SHA = re.compile(r"^[0-9a-f]{40}$")
_CONVENTIONAL = re.compile(r"^[a-z]+(?:\([a-z0-9-]+\))?!?: [^\n]{3,72}$")


def validate(_args):
    """Check layout, versions, workflow policy and action pins."""

    failures = [f"missing {name}" for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    failures += _check_python_layout()
    failures += _check_versions()
    workflows = _load_workflows()
    pins = _pins()
    for name, document in workflows.items():
        if name in GENERATED_WORKFLOWS:
            failures += check_generated_workflow(document, name)
        else:
            failures += _check_run_steps(document, name)
            failures += _check_permissions(document, name)
            if name == "release.yml":
                failures += _check_release_workflow(document)
        failures += _check_uses(document, pins, name)
    failures += _check_uses(load_yaml(ROOT / "action.yml"), pins, "action.yml")
    failures += _check_lefthook()
    failures += _check_pixi_tasks()
    failures += _check_action_contract(load_yaml(ROOT / "action.yml"))
    failures += _check_sandbox()
    failures += _check_devcontainer()
    failures += _check_docs()
    failures += _check_coverage_gate()
    if failures:
        raise AutomationError("\n".join(failures))
    if shutil.which("actionlint"):
        run(
            [
                "actionlint",
                "-shellcheck=",
                *sorted(f".github/workflows/{name}" for name in workflows),
            ]
        )
    else:
        print("actionlint is not installed; workflow syntax was not linted.", file=sys.stderr)
    print(
        f"Layout, versions, {len(workflows)} workflow(s), action pins and coverage gate validated."
    )


def _check_python_layout():
    failures = []
    for path in (ROOT / "scripts").rglob("*"):
        if path.is_file() and path.suffix != ".py" and "__pycache__" not in path.parts:
            failures.append(f"non-Python file under scripts/: {path.relative_to(ROOT)}")
    package = ROOT / PACKAGE
    if not (package / "__init__.py").is_file():
        failures.append(f"the package must live in {PACKAGE}/ at the repository root")
    for module in ("discovery", "validation", "duplicates", "plan", "gitops", "github", "submit"):
        if not (package / f"{module}.py").is_file():
            failures.append(f"missing core module: {module}.py")
    if (ROOT / "src").exists():
        failures.append("there is no src/ layout here: the package lives at the repository root")
    return failures


def _check_versions():
    project = read_toml(ROOT / "pyproject.toml")["project"]["version"]
    manifest = read_toml(ROOT / "pixi.toml")["workspace"]["version"]
    identity = read_toml(ROOT / "config/project.toml")["project"]["version"]
    # One declaration, in _version.py; everything else imports it.
    source = (ROOT / PACKAGE / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"', source, re.MULTILINE)
    if match is None:
        return [f"{PACKAGE}/_version.py has no __version__"]
    reexport = (ROOT / PACKAGE / "__init__.py").read_text(encoding="utf-8")
    if "from ._version import __version__" not in reexport:
        return [f"{PACKAGE}/__init__.py must re-export __version__ from _version.py"]
    versions = {project, manifest, identity, match.group(1)}
    if len(versions) != 1:
        return [f"versions disagree: {sorted(versions)}"]
    return []


def _load_workflows():
    documents = {}
    for path in sorted((ROOT / ".github/workflows").glob("*.yml")):
        documents[path.name] = load_yaml(path)
    missing = REQUIRED_WORKFLOWS - set(documents)
    extra = set(documents) - REQUIRED_WORKFLOWS - GENERATED_WORKFLOWS
    failures = [f"missing workflow: {name}" for name in sorted(missing)]
    failures += [f"unexpected workflow: {name}" for name in sorted(extra)]
    if failures:
        raise AutomationError("\n".join(failures))
    return documents


def _pins():
    records = json.loads((ROOT / "config/actions.lock.json").read_text(encoding="utf-8"))["actions"]
    return {record["repository"]: record["commit"] for record in records}


def _check_run_steps(document, name):
    failures = []
    for job_name, job in document.get("jobs", {}).items():
        for step in job.get("steps", []):
            if "run" not in step:
                continue
            lines = [line.strip() for line in step["run"].splitlines() if line.strip()]
            if len(lines) != 1 or not lines[0].startswith("pixi run "):
                failures.append(f"{name}/{job_name}: run steps must invoke exactly one Pixi task")
            elif "&&" in lines[0] or ";" in lines[0] or "|" in lines[0]:
                failures.append(f"{name}/{job_name}: run steps must not chain shell commands")
    return failures


def _check_uses(document, pins, name):
    failures = []
    containers = [document.get("runs", {})]
    containers += list(document.get("jobs", {}).values())
    for container in containers:
        for step in container.get("steps", []):
            reference = step.get("uses")
            if not reference or reference.startswith("./"):
                continue
            action, _, commit = reference.partition("@")
            if not _SHA.match(commit) or pins.get(action) != commit:
                failures.append(f"{name}: {action} is not pinned to config/actions.lock.json")
    return failures


def _check_permissions(document, name):
    if document.get("permissions") != {"contents": "read"}:
        return [f"{name}: the workflow must default to contents: read"]
    return []


def _check_release_workflow(document):
    """The release workflow cuts tags and a GitHub Release only: no wheel, no assets."""
    failures = []
    repository = read_toml(ROOT / "config/project.toml")["project"]["repository"]
    jobs = document.get("jobs", {})
    commands = set()
    forbidden = ("pip ", "twine", "hatch", "upload-artifact", "gh release upload")
    for job_name, job in jobs.items():
        permissions = job.get("permissions") or {}
        if permissions.get("contents") == "write":
            guard = str(job.get("if", "")).strip()
            if repository not in guard or "refs/heads/main" not in guard:
                failures.append(
                    f"release.yml/{job_name}: contents: write job must guard on {repository!r} "
                    "and refs/heads/main"
                )
        for step in job.get("steps", []):
            raw = " ".join(str(step.get(field, "")) for field in ("uses", "run") if field in step)
            for token in forbidden:
                if token in raw:
                    failures.append(
                        f"release.yml/{job_name}: forbidden build/asset operation {token!r}"
                    )
            run_line = step.get("run", "").strip()
            if run_line.startswith("pixi run "):
                commands.add(run_line.split()[-1])
    for required in ("release-plan", "release-publish"):
        if required not in commands:
            failures.append(f"release.yml must invoke 'pixi run --locked {required}'")
    return failures


def _check_lefthook():
    hooks = load_yaml(ROOT / "lefthook.yml")
    failures = []
    for hook in ("commit-msg", "pre-commit", "pre-push"):
        if hook not in hooks:
            failures.append(f"lefthook.yml is missing the {hook} hook")
            continue
        for command in hooks[hook].get("commands", {}).values():
            if not command.get("run", "").startswith("pixi run "):
                failures.append(f"lefthook {hook} must run a named Pixi task")
    return failures


def _check_pixi_tasks():
    """Every Pixi task must exist in the dispatcher, and every feature must exist."""
    import ast

    manifest = read_toml(ROOT / "pixi.toml")
    tasks = manifest.get("tasks", {})
    source = (ROOT / "scripts/run.py").read_text(encoding="utf-8")
    commands = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "COMMANDS":
            commands = {key.value for key in node.value.keys}
    failures = []
    for task, command in tasks.items():
        if task == "scripts":
            continue
        if f"python scripts/run.py {task}" != command:
            failures.append(f"pixi task {task!r} must call its dispatcher command")
        elif task not in commands:
            failures.append(f"pixi task {task!r} has no command in scripts/run.py")
    features = set(manifest.get("feature", {}))
    for environment, settings in manifest.get("environments", {}).items():
        unknown = set(settings.get("features", [])) - features
        if unknown:
            failures.append(f"environment {environment!r} uses unknown features: {sorted(unknown)}")
    return failures


def _check_sandbox():
    """The offline transport plan must match the workspace it packs."""
    config = read_toml(ROOT / SANDBOX_CONFIG)
    manifest = read_toml(ROOT / "pixi.toml")
    documents = {name: load_yaml(path) for name, path in _workflow_paths().items()}
    failures = check_sandbox_config(config, manifest, documents)
    failures += _check_sandbox_pin(manifest)
    return failures


def _workflow_paths():
    return {path.name: path for path in sorted((ROOT / ".github/workflows").glob("*.yml"))}


def _check_sandbox_pin(manifest):
    """The recorded CLI version must be the one the offline environment installs."""
    pin = json.loads((ROOT / SANDBOX_BOOTSTRAP).read_text(encoding="utf-8"))
    dependency = (
        manifest.get("feature", {})
        .get("offline", {})
        .get("dependencies", {})
        .get("pixi-sandbox", {})
    )
    expected = {"version": f"=={pin['version']}", "channel": pin["channel"]}
    if dependency != expected:
        return [
            "the offline feature must install the pinned sandbox tool "
            f"({pin['tool']} {pin['version']} from {pin['channel']})"
        ]
    return []


def pixi_versions(documents):
    """Every `pixi-version` input any workflow pins."""
    versions = set()
    for document in documents.values():
        for job in document.get("jobs", {}).values():
            for step in job.get("steps", []):
                value = (step.get("with") or {}).get("pixi-version")
                if value:
                    versions.add(value)
    return versions


def check_sandbox_config(config, manifest, documents=None):
    """Pure checks for `pixi-sandbox.toml` against the Pixi workspace."""
    errors = []
    if config.get("schema") not in (1, 2):
        errors.append(f"{SANDBOX_CONFIG}: schema {config.get('schema')!r} is not supported (1..=2)")
    prefix = config.get("branch_prefix", "sandbox")
    if not SAFE_SLUG.match(prefix):
        errors.append(f"{SANDBOX_CONFIG}: branch_prefix {prefix!r} is not a safe branch component")
    if config.get("cargo_vendor") is not False:
        errors.append(
            f"{SANDBOX_CONFIG}: cargo_vendor must be false; this repository has no Cargo.lock"
        )
    environments = set(manifest.get("environments", {}))
    platforms = set(manifest.get("workspace", {}).get("platforms", []))
    runners = config.get("runners", {})
    bundles = config.get("bundle", [])
    if not bundles:
        errors.append(f"{SANDBOX_CONFIG}: at least one [[bundle]] is required")
    names = set()
    for bundle in bundles:
        name = bundle.get("name", "")
        if not SAFE_SLUG.match(name):
            errors.append(f"{SANDBOX_CONFIG}: bundle name {name!r} must be lowercase slugs")
        if name in names:
            errors.append(f"{SANDBOX_CONFIG}: bundle {name!r} is declared twice")
        names.add(name)
        if bundle.get("cargo_vendor") is True:
            errors.append(f"{SANDBOX_CONFIG}: bundle {name!r} re-enables cargo_vendor")
        bundle_environments = bundle.get("environments", [])
        if not bundle_environments:
            errors.append(f"{SANDBOX_CONFIG}: bundle {name!r} has no environments")
        for environment in bundle_environments:
            if environment not in environments:
                errors.append(
                    f"{SANDBOX_CONFIG}: bundle {name!r} names environment {environment!r}, "
                    f"which pixi.toml does not define ({sorted(environments)})"
                )
        bundle_platforms = bundle.get("platforms", [])
        if not bundle_platforms:
            errors.append(f"{SANDBOX_CONFIG}: bundle {name!r} has no platforms")
        for platform in bundle_platforms:
            if platform not in platforms:
                errors.append(
                    f"{SANDBOX_CONFIG}: bundle {name!r} targets {platform!r}, "
                    f"which pixi.toml does not support ({sorted(platforms)})"
                )
            if not runners.get(platform):
                errors.append(
                    f"{SANDBOX_CONFIG}: {platform!r} needs an explicit runners.{platform} label"
                )
    for platform in runners:
        if platform not in STANDARD_PLATFORMS:
            errors.append(f"{SANDBOX_CONFIG}: unknown platform in [runners]: {platform!r}")
    errors += _check_budgets(config.get("budgets", {}))
    errors += _check_workflow_policy(config.get("workflow"), documents or {})
    return errors


def _check_budgets(budgets):
    errors = []
    defaults = {
        "max_blob_mib": 95,
        "max_transport_mib": 2048,
        "max_repository_push_mib": 2048,
        "max_restore_required_mib": 8192,
    }
    for key, ceiling in defaults.items():
        value = budgets.get(key, ceiling)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(f"{SANDBOX_CONFIG}: budgets.{key} must be a positive integer")
        elif key == "max_blob_mib" and value > 95:
            errors.append(f"{SANDBOX_CONFIG}: budgets.max_blob_mib must be at most 95 MiB")
    return errors


def _check_workflow_policy(policy, documents):
    errors = []
    if policy is None:
        return [f"{SANDBOX_CONFIG}: [workflow] is required so the publisher stays least-privilege"]
    if policy.get("permissions") is not True:
        errors.append(
            f"{SANDBOX_CONFIG}: workflow.permissions must be true "
            "(contents: read top-level, contents: write only on publish)"
        )
    if policy.get("setup_pixi_cache") is not False:
        errors.append(f"{SANDBOX_CONFIG}: workflow.setup_pixi_cache must be false (ADR-18)")
    pinned = policy.get("pixi_version")
    versions = pixi_versions(documents)
    if not pinned:
        errors.append(f"{SANDBOX_CONFIG}: workflow.pixi_version must pin the Pixi release")
    elif versions and versions != {pinned}:
        errors.append(
            f"{SANDBOX_CONFIG}: workflow.pixi_version {pinned!r} disagrees with the workflows "
            f"({sorted(versions)})"
        )
    concurrency = policy.get("concurrency") or {}
    if not str(concurrency.get("group", "")).strip():
        errors.append(f"{SANDBOX_CONFIG}: workflow.concurrency.group must be a non-empty label")
    for field, minutes in (policy.get("timeouts") or {}).items():
        if field not in {"plan", "publish"}:
            errors.append(f"{SANDBOX_CONFIG}: unknown workflow.timeouts field {field!r}")
        elif not isinstance(minutes, int) or not 1 <= minutes <= MAX_TIMEOUT_MINUTES:
            errors.append(
                f"{SANDBOX_CONFIG}: workflow.timeouts.{field} must be 1..{MAX_TIMEOUT_MINUTES}"
            )
    for field in ("push_paths", "relock_paths"):
        paths = policy.get(field)
        if paths is not None and not paths:
            errors.append(f"{SANDBOX_CONFIG}: workflow.{field} must be omitted or non-empty")
    return errors


def check_generated_workflow(document, name):
    """Policy for a workflow pixi-sandbox generated rather than this repository."""
    errors = []
    if document.get("permissions") != {"contents": "read"}:
        errors.append(f"{name}: a generated workflow must default to contents: read")
    jobs = document.get("jobs", {})
    if not jobs:
        errors.append(f"{name}: a generated workflow must declare jobs")
    for job_name, job in jobs.items():
        permissions = job.get("permissions") or {}
        if permissions.get("contents") == "write" and not str(job.get("if", "")).strip():
            errors.append(
                f"{name}/{job_name}: a job with contents: write needs an explicit guard in `if`"
            )
    return errors


def _check_devcontainer():
    """The container mirrors the repository's pins instead of inventing its own."""
    import json

    failures = []
    try:
        document = json.loads(
            (ROOT / DEVCONTAINER / "devcontainer.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as error:
        return [f".devcontainer/devcontainer.json is not strict JSON: {error}"]
    if not str(document.get("name", "")).strip():
        failures.append("devcontainer.json must name the container")
    dockerfile = document.get("build", {}).get("dockerfile")
    if not dockerfile or not (ROOT / DEVCONTAINER / dockerfile).is_file():
        failures.append("devcontainer.json must build from an existing Dockerfile")
    post_create = str(document.get("postCreateCommand", ""))
    script = DEVCONTAINER / "post-create.sh"
    if "post-create.sh" not in post_create:
        failures.append("devcontainer.json must provision through .devcontainer/post-create.sh")
    elif not script.is_file():
        failures.append(".devcontainer/post-create.sh is missing")
    else:
        failures += _check_post_create(script)
    mounts = " ".join(document.get("mounts", []))
    if "/.pixi" not in mounts or "volume" not in mounts:
        failures.append(
            "the .pixi directory must be a volume: case-insensitive bind mounts break it"
        )
    if document.get("containerEnv", {}).get("PIXI_NO_TELEMETRY") != "1":
        failures.append("the container must set PIXI_NO_TELEMETRY=1")
    failures += _check_devcontainer_extensions(document)
    failures += _check_dockerfile_pins(ROOT / DEVCONTAINER / "Dockerfile")
    return failures


def _check_post_create(script):
    text = script.read_text(encoding="utf-8")
    failures = []
    for forbidden in FORBIDDEN_IN_POST_CREATE:
        if forbidden in text:
            failures.append(
                f".devcontainer/post-create.sh must delegate to pixi tasks, not run {forbidden!r}"
            )
    tasks = read_toml(ROOT / "pixi.toml").get("tasks", {})
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith(("pixi run", "pixi --version")):
            continue
        parts = [part for part in stripped.split() if not part.startswith("-")]
        if parts[:2] == ["pixi", "run"] and len(parts) > 2 and parts[2] not in tasks:
            failures.append(f".devcontainer/post-create.sh runs unknown task {parts[2]!r}")
    if "--locked" not in text:
        failures.append(".devcontainer/post-create.sh must use pixi run --locked")
    return failures


def _check_devcontainer_extensions(document):
    extensions = document.get("customizations", {}).get("vscode", {}).get("extensions", [])
    recommended = json.loads((ROOT / ".vscode/extensions.json").read_text(encoding="utf-8"))[
        "recommendations"
    ]
    missing = sorted(set(recommended) - set(extensions))
    return [f"the devcontainer omits recommended extension {name}" for name in missing]


def _check_dockerfile_pins(path):
    text = path.read_text(encoding="utf-8")
    failures = []
    failures += _check_base_image_digest(text)
    if re.search(r"curl[^\n]*\|\s*(?:ba)?sh", text):
        failures.append(".devcontainer/Dockerfile must not pipe a download into a shell")
    if "sha256sum -c" not in text:
        failures.append(".devcontainer/Dockerfile must verify the Pixi download checksum")
    match = re.search(r"^ARG PIXI_VERSION=(\S+)", text, re.MULTILINE)
    if match is None:
        return [".devcontainer/Dockerfile must declare ARG PIXI_VERSION"]
    pinned = _workflow_pixi_pins()
    sandbox = read_toml(ROOT / SANDBOX_CONFIG).get("workflow", {}).get("pixi_version")
    expected = pinned | ({sandbox} if sandbox else set())
    if expected and expected != {match.group(1)}:
        failures.append(
            f".devcontainer/Dockerfile PIXI_VERSION {match.group(1)!r} disagrees with "
            f"the repository pins ({sorted(expected)})"
        )
    return failures


def _check_base_image_digest(text):
    """The base image must be pinned by digest, directly or through an ARG default."""
    from_line = re.search(r"^FROM\s+(\S+)", text, re.MULTILINE)
    if from_line is None:
        return [".devcontainer/Dockerfile has no FROM line"]
    reference = from_line.group(1)
    variable = re.fullmatch(r"\$\{(\w+)\}|\$(\w+)", reference)
    if variable:
        name = variable.group(1) or variable.group(2)
        default = re.search(rf"^ARG\s+{name}=([^\s]+)", text, re.MULTILINE)
        if default is None:
            return [f".devcontainer/Dockerfile builds from ${{{name}}} with no pinned default"]
        reference = default.group(1)
        if not re.search(r"@sha256:[0-9a-f]{64}$", reference):
            return [
                f".devcontainer/Dockerfile builds from ${{{name}}} with no digest-pinned default"
            ]
    if not re.search(r"@sha256:[0-9a-f]{64}$", reference):
        return [".devcontainer/Dockerfile must pin its base image by digest"]
    return []


def _workflow_pixi_pins():
    documents = {name: load_yaml(path) for name, path in _workflow_paths().items()}
    return pixi_versions(documents)


def _check_docs():
    """The README stays short and links every document kept in docs/."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    lines = readme.splitlines()
    failures = []
    if len(lines) > MAX_README_LINES:
        failures.append(
            f"README.md has {len(lines)} lines; keep it under {MAX_README_LINES} and move detail "
            "into docs/"
        )
    for path in sorted((ROOT / "docs").glob("*.md")):
        relative = path.relative_to(ROOT).as_posix()
        if f"({relative})" not in readme:
            failures.append(f"README.md does not link {relative}")
    for extra in ("API.md", "CONTRIBUTING.md", "AGENTS.md"):
        if f"({extra})" not in readme:
            failures.append(f"README.md does not link {extra}")
    failures += _check_api_doc()
    guide = (ROOT / "docs/GUIDE.md").read_text(encoding="utf-8")
    headings = {_slug(line) for line in guide.splitlines() if line.startswith("#")}
    for anchor in re.findall(r"^- \[.+?\]\(#([a-z0-9-]+)\)$", guide, re.MULTILINE):
        if anchor not in headings:
            failures.append(f"docs/GUIDE.md links #{anchor} but has no such heading")
    return failures


def _check_api_doc():
    """API.md must document every input and output that action.yml declares."""
    failures = []
    api = (ROOT / "API.md").read_text(encoding="utf-8")
    action = load_yaml(ROOT / "action.yml")
    for kind in ("inputs", "outputs"):
        for name in sorted(action.get(kind, {})):
            if f"| `{name}` |" not in api:
                failures.append(f"API.md does not document the {kind[:-1]} {name!r}")
    for section in ("## Inputs", "## Outputs", "## CLI reference", "## Python API"):
        if section not in api:
            failures.append(f"API.md is missing the {section[3:]!r} section")
    return failures


def _slug(text):
    heading = text.lstrip("#").strip().lower()
    heading = re.sub(r"[^a-z0-9\s-]", "", heading)
    return re.sub(r"\s+", "-", heading)


def _check_action_contract(action):
    """The composite action runs this repository's scripts; nothing is published."""
    steps = action.get("runs", {}).get("steps", [])
    inputs = action.get("inputs", {})
    failures = []
    if action.get("runs", {}).get("using") != "composite":
        failures.append("action.yml must stay a composite action")
    for retired in ("version", "install-from", "wheel-url", "wheel-sha256"):
        if retired in inputs:
            failures.append(f"action.yml still declares the retired {retired!r} input")
    if not any(step.get("uses", "").startswith("actions/setup-python@") for step in steps):
        failures.append("action.yml must install Python before running the package")
    invocations = [step for step in steps if _calls_dispatcher(step.get("run", ""))]
    if not invocations:
        failures.append(f"action.yml must run the dispatcher ({DISPATCHER})")
    for step in steps:
        command = step.get("run", "").strip()
        if not command or _is_runtime_install(command) or _calls_dispatcher(command):
            continue
        failures.append(
            f"action.yml step {step.get('name', '?')!r} must call the dispatcher "
            f"({DISPATCHER}) or install the pinned runtime dependency"
        )
    for step in invocations:
        if step.get("env", {}).get("PYTHONPATH") != "${{ github.action_path }}":
            failures.append(
                f"action.yml step {step.get('name', '?')!r} must put the action checkout on PYTHONPATH"
            )
    for step in invocations:
        # A renamed or dropped mapping here makes every token silently empty at
        # run time; the runtime diagnostics then say so, but only after a run.
        if not step.get("run", "").rstrip().endswith(" action"):
            continue
        if step.get("env", {}).get("INPUT_TOKEN") != "${{ inputs.github-token }}":
            failures.append(
                f"action.yml step {step.get('name', '?')!r} must pass inputs.github-token "
                "through INPUT_TOKEN"
            )
    commands = {step["run"].split()[-1] for step in invocations}
    known = _dispatcher_commands()
    for command in sorted(commands - known):
        failures.append(f"action.yml calls the unknown dispatcher command {command!r}")
    if {"action", "summary"} - commands:
        failures.append("action.yml must run both the submit and the summary steps")
    failures += _check_runtime_pin(steps)
    publish = read_toml(ROOT / "config/project.toml").get("publish", {})
    for key in ("pypi", "release"):
        if publish.get(key) is not False:
            failures.append(f"config/project.toml must record publish.{key} = false")
    if any(
        "pip install" in step.get("run", "") and "ACTION_PATH" in step.get("run", "")
        for step in steps
    ):
        failures.append("action.yml must not install the checkout; it runs it from PYTHONPATH")
    return failures


def _calls_dispatcher(command):
    return command.strip().startswith(f'python "$ACTION_PATH/{DISPATCHER}"')


def _is_runtime_install(command):
    return "pip install" in command and _runtime_pyyaml_pin() in command


def _runtime_pyyaml_pin():
    pinned = read_toml(ROOT / "config/project.toml").get("runtime", {}).get("pyyaml", "")
    return f"pyyaml=={pinned}" if pinned else ""


def _check_runtime_pin(steps):
    """The pinned runtime dependency in action.yml must match config/project.toml."""
    runtime = read_toml(ROOT / "config/project.toml").get("runtime", {})
    pinned = runtime.get("pyyaml")
    if not pinned:
        return ["config/project.toml must record the runtime.pyyaml pin"]
    installs = " ".join(step.get("run", "") for step in steps)
    if f'"pyyaml=={pinned}"' not in installs and f"pyyaml=={pinned}" not in installs:
        return [f"action.yml must install pyyaml=={pinned}"]
    requirement = read_toml(ROOT / "pyproject.toml")["project"]["dependencies"]
    lowered = [item for item in requirement if item.startswith("pyyaml")]
    if not lowered:
        return ["pyproject.toml must declare pyyaml as a dependency"]
    match = re.fullmatch(r"pyyaml>=([0-9.]+)", lowered[0].strip())
    if match is None or _version_tuple(match.group(1)) > _version_tuple(str(pinned)):
        return [f"pyproject.toml must require pyyaml>={pinned} or lower"]
    return []


def _version_tuple(text):
    return tuple(int(part) for part in re.findall(r"\d+", text))


def _dispatcher_commands():
    """Every command `scripts/run.py` can dispatch, read without importing it."""
    import ast

    source = (ROOT / DISPATCHER).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "COMMANDS":
            return {key.value for key in node.value.keys}
    return set()


def _check_coverage_gate():
    gate = read_toml(ROOT / "pyproject.toml")["tool"]["coverage"]["report"]["fail_under"]
    if gate < MINIMUM_COVERAGE:
        return [f"the coverage gate is {gate}, below the required {MINIMUM_COVERAGE}"]
    return []


def python_format(_args):
    run(["ruff", "format", *SOURCES])


def python_format_check(_args):
    run(["ruff", "format", "--check", *SOURCES])


def python_lint(_args):
    run(["ruff", "check", *SOURCES])


def python_type_check(_args):
    run(["mypy"])


def python_test(args):
    command = ["python", "-m", "pytest"]
    run([*command, *(args or ["-q"])])


def coverage(_args):
    run(
        [
            "python",
            "-m",
            "pytest",
            "--cov",
            "--cov-report=term-missing",
            "--cov-report=xml:coverage.xml",
            "--cov-fail-under=90",
            "-q",
        ]
    )


def ci(args):
    if args:
        raise AutomationError("ci takes no arguments.")
    for task in (validate, python_lint, python_format_check, python_type_check, coverage):
        task([])
    print("Local CI passed: validate, lint, format, types, coverage.")
