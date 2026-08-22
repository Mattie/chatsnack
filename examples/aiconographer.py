"""Turn source text into one selected, compiled SVG icon."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


EXAMPLE_ROOT = Path(__file__).resolve().parent
PROMPT_ROOT = EXAMPLE_ROOT / "aiconographer_prompts"
COMPILER_ROOT = EXAMPLE_ROOT / "aiconographer_support"
ALIASES = ("ash", "birch", "cedar", "dune", "ember", "flint")
SCORE_WEIGHTS = {
    "article_specificity": 0.30,
    "legibility_48px": 0.25,
    "professional_craft": 0.20,
    "silhouette_and_composition": 0.15,
    "two_fill_style_compliance": 0.10,
}


def parse_json(text: str) -> dict[str, Any]:
    """Read a JSON object from a direct model response with optional code fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.IGNORECASE)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"Expected a JSON object, received: {text[:200]!r}")
    return json.loads(stripped[start : end + 1])


def slugify(title: str) -> str:
    """Turn a short label into the compiler's lowercase slug format."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "source-icon"


def run_checked(command: list[str]) -> None:
    """Run one deterministic compiler command and surface its output on failure."""
    subprocess.run(command, check=True)


def compile_sheet(
    node: str,
    compiler_root: Path,
    deps_root: Path,
    sheet_path: Path,
    output: Path,
    source_path: Path,
) -> str | None:
    """Compile one sheet and return a concise rejection reason instead of ending the run."""
    command = [
        node,
        str(compiler_root / "scripts" / "process-sheet.mjs"),
        "--input",
        str(sheet_path),
        "--output",
        str(output),
        "--deps-root",
        str(deps_root),
        "--article",
        str(source_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if result.returncode == 0:
        return None
    details = [line.strip() for line in (result.stderr + result.stdout).splitlines() if line.strip()]
    return details[-1] if details else f"Compiler exited with status {result.returncode}."


def ensure_dependencies(compiler_root: Path, deps_root: Path) -> None:
    """Install the copied compiler's pinned dependencies in a temporary directory."""
    if (deps_root / "node_modules").is_dir():
        return
    deps_root.mkdir(parents=True, exist_ok=True)
    scripts = compiler_root / "scripts"
    shutil.copy2(scripts / "package.json", deps_root / "package.json")
    shutil.copy2(scripts / "package-lock.json", deps_root / "package-lock.json")
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required to stage the Aiconographer compiler dependencies.")
    run_checked([npm, "ci", "--prefix", str(deps_root)])


def preflight_tooling(compiler_root: Path, deps_root: Path) -> str:
    """Check the local compiler before spending any model or image-generation calls."""
    required = (
        compiler_root / "scripts" / "process-sheet.mjs",
        compiler_root / "scripts" / "finalize-winner.mjs",
        compiler_root / "scripts" / "package.json",
        compiler_root / "scripts" / "package-lock.json",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Aiconographer compiler files are missing: {missing}")
    node = shutil.which("node.exe") or shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is required for the Aiconographer compiler.")
    ensure_dependencies(compiler_root, deps_root)
    return node


def load_prompt(name: str, utensils: list[Any] | None = None):
    """Load one authored chat and attach runtime capabilities at construction."""
    from chatsnack import Chat

    template = Chat(name=name)
    template.load(PROMPT_ROOT / f"{name}.yml")
    if not utensils:
        return template
    chat = Chat(
        name=template.name,
        params=template.params,
        messages=template.messages,
        utensils=utensils,
    )
    template.close_session()
    return chat


def first_user_message(chat: Any) -> str:
    """Return the expanded user prompt from a completed chat for run provenance."""
    for message in chat.messages:
        content = message.get("user")
        if isinstance(content, str):
            return content
        if isinstance(content, dict) and isinstance(content.get("text"), str):
            return content["text"]
    raise ValueError("The completed artist chat did not retain its user prompt.")


def sheet_padding_issues(node: str, deps_root: Path, sheet_path: Path) -> list[str]:
    """Use the compiler's Sharp dependency to catch art inside a four-percent tile margin."""
    sharp_module = deps_root / "node_modules" / "sharp"
    script = r"""
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const sharp = require(process.argv[1]);
const { data, info } = await sharp(process.argv[2])
  .removeAlpha()
  .raw()
  .toBuffer({ resolveWithObject: true });
const findings = [];
for (let row = 0; row < 2; row += 1) {
  for (let col = 0; col < 3; col += 1) {
    const x0 = Math.floor((info.width * col) / 3);
    const x1 = Math.floor((info.width * (col + 1)) / 3);
    const y0 = Math.floor((info.height * row) / 2);
    const y1 = Math.floor((info.height * (row + 1)) / 2);
    const margin = Math.max(2, Math.floor(Math.min(x1 - x0, y1 - y0) * 0.04));
    let foreground = 0;
    for (let y = y0; y < y1; y += 1) {
      for (let x = x0; x < x1; x += 1) {
        if (x >= x0 + margin && x < x1 - margin && y >= y0 + margin && y < y1 - margin) continue;
        const offset = (y * info.width + x) * info.channels;
        if (Math.min(data[offset], data[offset + 1], data[offset + 2]) < 210) foreground += 1;
      }
    }
    // Ignore isolated antialiased specks while still rejecting shapes that reach the safety band.
    if (foreground > 25) findings.push({ cell: row * 3 + col + 1, foreground, margin });
  }
}
console.log(JSON.stringify(findings));
"""
    result = subprocess.run(
        [node, "--input-type=module", "-e", script, str(sharp_module), str(sheet_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    findings = json.loads(result.stdout)
    return [
        f"Cell {item['cell']} enters its {item['margin']}px safety margin "
        f"({item['foreground']} foreground pixels)."
        for item in findings
    ]


def require_empty_directory(path: Path) -> None:
    """Create a run directory without overwriting an earlier icon run."""
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {path}")
    path.mkdir(parents=True, exist_ok=True)


def read_source(inputfile: Path | None) -> str:
    """Read nonempty UTF-8 source material from a file or one interactive prompt."""
    if inputfile is None:
        try:
            source_text = input("Describe the icon’s subject, vibe, or source material: ")
        except EOFError as error:
            raise ValueError("No source material was provided.") from error
    else:
        try:
            source_text = inputfile.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"Input file must contain UTF-8 text: {inputfile}") from error

    if not source_text.strip():
        raise ValueError("Source material cannot be empty.")
    return source_text.strip()


def find_scorecard(files: list[Any]) -> Any:
    """Find the captured Code Interpreter scorecard by its requested filename."""
    for item in files:
        if item.filename == "aiconographer-scorecard.json":
            return item
    available = ", ".join(item.filename or "<unnamed>" for item in files)
    raise RuntimeError(f"The judge did not return aiconographer-scorecard.json. Files: {available}")


def validate_scorecard(scorecard: dict[str, Any]) -> None:
    """Validate the judge contract and make its weighted arithmetic deterministic."""
    candidates = scorecard.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(ALIASES):
        raise ValueError("The scorecard must contain exactly six candidates.")
    by_alias = {str(item.get("alias", "")).lower(): item for item in candidates}
    if set(by_alias) != set(ALIASES):
        raise ValueError(f"The scorecard aliases must be exactly: {', '.join(ALIASES)}")
    for alias, item in by_alias.items():
        expected_total = 0.0
        for field, weight in SCORE_WEIGHTS.items():
            score = item.get(field)
            if not isinstance(score, (int, float)) or isinstance(score, bool) or not 1 <= score <= 5:
                raise ValueError(f"{alias}.{field} must be a score from 1 to 5.")
            expected_total += score * weight
        total = item.get("weighted_total")
        if not isinstance(total, (int, float)) or isinstance(total, bool):
            raise ValueError(f"{alias}.weighted_total must be numeric.")
        expected_total = round(expected_total, 2)
        if abs(total - expected_total) > 0.01:
            item["reported_weighted_total"] = total
            item["weighted_total"] = expected_total
        if not isinstance(item.get("notes"), str) or not item["notes"].strip():
            raise ValueError(f"{alias}.notes must be a non-empty string.")
    winner = str(scorecard.get("winner", "")).lower()
    runner_up = str(scorecard.get("runner_up", "")).lower()
    if winner not in by_alias or runner_up not in by_alias or winner == runner_up:
        raise ValueError("Winner and runner_up must be different known aliases.")
    for field in ("reason", "refinement"):
        if not isinstance(scorecard.get(field), str) or not scorecard[field].strip():
            raise ValueError(f"The scorecard needs a non-empty {field}.")


def run(args: argparse.Namespace, source_text: str) -> Path:
    """Generate, compile, judge, and finalize one source-material icon run."""
    load_dotenv(Path(__file__).with_name(".env"))
    require_empty_directory(args.workdir)
    os.environ["CHATSNACK_BASE_DIR"] = str(args.workdir / "chatsnack-data")
    node = preflight_tooling(args.compiler_root, args.deps_root)

    from chatsnack import Chat, ChatFile, utensil

    slug = args.slug or slugify(args.output_svg.stem)
    source_path = args.workdir / "source.txt"
    source_path.write_text(source_text, encoding="utf-8")

    chats: list[Chat] = []
    try:
        planner = load_prompt("planner")
        chats.append(planner)
        plan_text = planner.ask(source_material=source_text)
        plan = parse_json(plan_text)
        if len(plan.get("concepts", [])) != 6:
            raise ValueError("The concept planner must return exactly six concepts.")
        (args.workdir / "concept-plan.json").write_text(
            json.dumps(plan, indent=2) + "\n", encoding="utf-8"
        )

        generation = None
        inspection = None
        generation_attempts: list[dict[str, Any]] = []
        compiled_root = args.workdir / "compiled"
        if args.sheet:
            sheet = ChatFile.from_reference(
                {"path": str(args.sheet.resolve()), "filename": args.sheet.name},
                kind="image",
            )
            padding_issues = sheet_padding_issues(
                node, args.deps_root, Path(sheet)
            )
            if padding_issues:
                inspection = {"accepted": False, "issues": padding_issues}
            else:
                inspection = {
                    "accepted": True,
                    "issues": [],
                    "check": "provided sheet passed deterministic padding checks",
                }
            if inspection.get("accepted") is not True:
                raise RuntimeError(
                    f"Provided sheet was rejected: {inspection.get('issues', [])}"
                )
            sheet_path = sheet.save_as(args.workdir / "candidate-sheet.png")
            compiler_issue = compile_sheet(
                node,
                args.compiler_root,
                args.deps_root,
                sheet_path,
                compiled_root,
                source_path,
            )
            if compiler_issue:
                raise RuntimeError(f"Provided sheet was rejected: {compiler_issue}")
        else:
            inspector = load_prompt("inspector")
            chats.append(inspector)
            image_tool = utensil.image_generation(
                model="gpt-image-2",
                quality="high",
                size="1536x1024",
                background="opaque",
            )
            artist = load_prompt("artist", utensils=[image_tool])
            chats.append(artist)
            sheet = None
            for attempt in range(1, args.attempts + 1):
                feedback = (
                    ""
                    if inspection is None
                    else f"Fix these rejected-sheet issues: {inspection['issues']}"
                )
                generation = artist.chat(
                    plan=json.dumps(plan, indent=2),
                    feedback=feedback,
                )
                if not generation.images:
                    raise RuntimeError("Image generation returned no captured image.")
                sheet = generation.images[0]
                attempt_sheet_path = sheet.save_as(
                    args.workdir / f"candidate-sheet-attempt-{attempt}.png"
                )
                padding_issues = sheet_padding_issues(
                    node, args.deps_root, attempt_sheet_path
                )
                if padding_issues:
                    inspection = {"accepted": False, "issues": padding_issues}
                else:
                    inspection_text = inspector.ask(images=[sheet])
                    inspection = parse_json(inspection_text)
                if inspection.get("accepted") is True:
                    attempt_compiled = args.workdir / f"compiled-attempt-{attempt}"
                    compiler_issue = compile_sheet(
                        node,
                        args.compiler_root,
                        args.deps_root,
                        attempt_sheet_path,
                        attempt_compiled,
                        source_path,
                    )
                    if compiler_issue:
                        inspection = {
                            "accepted": False,
                            "issues": [
                                f"Compiler rejected the sheet: {compiler_issue} "
                                "Keep coral and charcoal shapes separated by visible white "
                                "negative space; the two inks must not touch or overlap."
                            ],
                        }
                generation_attempts.append(
                    {
                        "attempt": attempt,
                        "prompt": first_user_message(generation),
                        "inspection": inspection,
                    }
                )
                if inspection.get("accepted") is True:
                    sheet_path = args.workdir / "candidate-sheet.png"
                    shutil.copy2(attempt_sheet_path, sheet_path)
                    attempt_compiled.rename(compiled_root)
                    break
                print(f"Sheet attempt {attempt} rejected: {inspection.get('issues', [])}")
            else:
                raise RuntimeError(f"No acceptable candidate sheet after {args.attempts} attempts.")
        assert sheet is not None and inspection is not None
        if generation is not None:
            (args.workdir / "generation-chat.yml").write_text(
                generation.yaml, encoding="utf-8"
            )
        (args.workdir / "sheet-inspection.json").write_text(
            json.dumps(inspection, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Captured image: {sheet.filename} -> {sheet_path}")
        if generation is not None:
            print(f"Chat views: {len(generation.images)} image, {len(generation.files)} file")

        review_root = compiled_root / "anonymous-review"
        review_images = [
            review_root / size / f"{alias}.png"
            for alias in ALIASES
            for size in ("192", "48")
        ]
        missing = [path for path in review_images if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Compiler review images are missing: {missing}")

        judge = load_prompt("judge", utensils=[utensil.code_interpreter])
        chats.append(judge)
        judging = judge.chat(
            source_material=source_text,
            images=review_images,
        )
        scorecard_file = find_scorecard(judging.files)
        scorecard_path = scorecard_file.save_as(
            args.workdir / "aiconographer-scorecard.json"
        )
        scorecard = json.loads(scorecard_file.read_bytes().decode("utf-8"))
        validate_scorecard(scorecard)

        review_map = json.loads(
            (args.workdir / "compiled" / "review-map.json").read_text(encoding="utf-8")
        )
        winner_alias = str(scorecard["winner"]).lower()
        winner = review_map["aliasMap"].get(winner_alias)
        if winner is None:
            raise ValueError(f"Judge returned an unknown winner alias: {winner_alias!r}")

        finalizer = args.compiler_root / "scripts" / "finalize-winner.mjs"
        run_checked(
            [
                node,
                str(finalizer),
                "--run",
                str(args.workdir / "compiled"),
                "--candidate",
                winner,
                "--slug",
                slug,
            ]
        )
        selection = json.loads(
            (args.workdir / "compiled" / "selection.json").read_text(encoding="utf-8")
        )
        validation = json.loads(
            (args.workdir / "compiled" / "validation.json").read_text(encoding="utf-8")
        )
        run_record = {
            "source_text": source_text,
            "concept_plan": plan,
            "generation_attempts": generation_attempts,
            "candidate_provider": (
                "provided sheet"
                if args.sheet
                else "chatsnack image_generation / gpt-image-2"
            ),
            "provided_sheet": str(args.sheet.resolve()) if args.sheet else None,
            "orchestrator_model": planner.model,
            "sheet_inspection": inspection,
            "source_sheet": validation["sourceSheet"],
            "compiler_tools": validation["toolVersions"],
            "scorecard_file": str(scorecard_path),
            "scorecard": scorecard,
            "selection": selection,
        }
        (args.workdir / "run-record.json").write_text(
            json.dumps(run_record, indent=2) + "\n", encoding="utf-8"
        )

        canonical = args.workdir / "compiled" / f"{slug}.svg"
        preview = args.workdir / "compiled" / f"{slug}-48.png"
        print(f"Captured judge file: {scorecard_file.filename} -> {scorecard_path}")
        print(f"Winner: {winner_alias} -> {winner}")
        print(f"Canonical SVG: {canonical}")
        print(f"48px preview: {preview}")
        return canonical
    finally:
        for chat in chats:
            chat.close_session()


def build_parser() -> argparse.ArgumentParser:
    """Build the small command-line surface for this one-off example."""
    default_deps = Path(tempfile.gettempdir()) / "chatsnack-aiconographer-deps"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_svg", type=Path, help="Destination for the selected SVG")
    parser.add_argument(
        "-i",
        "--inputfile",
        type=Path,
        help="UTF-8 source material; prompts interactively when omitted",
    )
    parser.add_argument("--sheet", type=Path, help="Resume from an existing 3-by-2 sheet")
    parser.add_argument(
        "--workdir",
        type=Path,
        help="New or empty directory for retained run evidence",
    )
    parser.add_argument("--slug", help="Internal slug; defaults to the output filename")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--compiler-root", type=Path, default=COMPILER_ROOT)
    parser.add_argument("--deps-root", type=Path, default=default_deps)
    return parser


def main(argv: list[str] | None = None) -> Path:
    """Run the CLI and copy the selected canonical SVG to the requested path."""
    args = build_parser().parse_args(argv)
    source_text = read_source(args.inputfile)
    if args.workdir is None:
        args.workdir = Path(tempfile.mkdtemp(prefix="chatsnack-aiconographer-"))
    print(f"Work directory: {args.workdir.resolve()}")

    canonical = run(args, source_text)
    args.output_svg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(canonical, args.output_svg)
    print(f"Final SVG: {args.output_svg.resolve()}")
    return args.output_svg


if __name__ == "__main__":
    main()
