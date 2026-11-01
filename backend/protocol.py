"""Deterministic Medici v1 syntax. Content is data, never instructions to execute."""
import hashlib
import re

HEADINGS = {"Materials", "Procedure", "Purpose", "Notes", "Expected results"}
ALIAS = r"[a-z][a-z0-9-]{0,39}"
REFERENCE = re.compile(r"@(" + ALIAS + r")(?![a-zA-Z0-9_-])")
SCOPE_POLICY = {
    "automaticTargets": "Only explicitly declared materials, numbered steps, and Expect statements.",
    "materialIdentity": "Declared cues are hypotheses to verify in footage, not proof of identity. Never identify contents by appearance alone.",
    "missingEvidence": "Mark obscured or unreadable evidence not verifiable; absence from view does not prove omission.",
    "measurements": "Procedure quantities are expected values, not observed measurements.",
    "extraEvents": "Undeclared items or actions cannot become automatic tracking targets. Manual observations remain available.",
}


def parse_protocol(text):
    errors, materials, steps = [], [], []
    invalid_materials = set()
    missing_reported = set()
    sections = {name: [] for name in HEADINGS}
    seen = set()
    section, title, current_step = None, None, None

    def error(line, message):
        errors.append({"line": line, "message": message})

    if not text.strip():
        return {"valid": True, "errors": [], "document": {
            "formatVersion": 1, "status": "draft", "title": None, "materials": [], "steps": [],
            "sections": {}, "sourceSha256": hashlib.sha256(text.encode()).hexdigest(),
        }}

    lines = text.splitlines()
    nonempty = [i for i, value in enumerate(lines) if value.strip()]
    fence_lines = set()
    if nonempty and re.fullmatch(r"```(?:text|markdown|md)?", lines[nonempty[0]].strip()):
        if len(nonempty) > 1 and lines[nonempty[-1]].strip() == "```":
            fence_lines = {nonempty[0], nonempty[-1]}
        else:
            error(nonempty[0] + 1, "Close the pasted code block with ``` or remove the opening code fence.")
    for number, original in enumerate(lines, 1):
        if number - 1 in fence_lines:
            continue
        raw = original.replace('\u00a0', ' ')
        line = raw.strip()
        if not line:
            continue
        if line.startswith("# "):
            if title is not None or seen:
                error(number, "Use at most one '# Title', before all sections.")
            else:
                title = line[2:].strip()
                if not title:
                    error(number, "Title cannot be empty.")
            continue
        if line.startswith("## "):
            heading = line[3:].strip()
            if heading not in HEADINGS:
                error(number, "Unknown section. Use ## Materials, ## Procedure, ## Purpose, ## Notes, or ## Expected results.")
                section = None
            elif heading in seen:
                error(number, f"Section '{heading}' is repeated.")
                section = None
            else:
                seen.add(heading)
                section = heading
                current_step = None
            continue
        if line.startswith("#"):
            error(number, "Only '# Title' and the documented '## Section' headings are supported.")
            continue
        if section is None:
            error(number, "Place content inside a named section.")
            continue
        if section == "Materials":
            fields = [field.strip() for field in line.split('|')]
            key_match = re.fullmatch(r"[-*•]\s+@(" + ALIAS + r")", fields[0])
            if key_match:
                invalid_materials.add(key_match[1])
            if len(fields) != 4 or not key_match:
                error(number, "Use four material fields: - @id | equipment/reagent/sample | name | label/appearance/unverifiable: cue. Spaces around | are optional.")
                continue
            alias, kind, name = key_match[1], fields[1].lower(), fields[2]
            if kind not in {'equipment', 'reagent', 'sample'}:
                error(number, f"Material @{alias}: unknown kind '{fields[1]}'. Choose equipment (including pipettes and disposable tips), reagent, or sample.")
                continue
            cue_match = re.fullmatch(r"(label|appearance|unverifiable)\s*:\s*(\S.*)", fields[3], re.I)
            if not cue_match:
                error(number, f"Material @{alias}: the last field must begin with label:, appearance:, or unverifiable: followed by a cue. Example: appearance: clear disposable pipette tip.")
                continue
            cue_type, cue = cue_match[1].lower(), cue_match[2]
            if not name.strip() or not cue.strip():
                error(number, "Material name and identity cue cannot be empty.")
            if any(m["key"] == alias for m in materials):
                error(number, f"Material @{alias} is declared more than once.")
            if cue_type == "appearance" and kind != "equipment":
                error(number, "Reagents and samples need a label cue or 'unverifiable:'; appearance cannot establish their identity.")
            if "@" in name or "@" in cue or "|" in cue:
                error(number, "Use @references only in steps, details, or notes; material fields cannot contain @ or extra | separators.")
            materials.append({"key": alias, "kind": kind, "name": name.strip(), "cueType": cue_type,
                              "cue": cue.strip(), "identityVerifiable": cue_type != "unverifiable", "sourceLine": number})
            invalid_materials.discard(alias)
        elif section == "Procedure":
            match = re.fullmatch(r"([1-9][0-9]*)\. (.+)", line)
            if match:
                order, description = int(match[1]), match[2].strip()
                if order != len(steps) + 1:
                    error(number, f"Steps must be consecutive, starting at 1. Expected {len(steps) + 1}.")
                refs = list(dict.fromkeys(REFERENCE.findall(description)))
                if not refs:
                    error(number, "Each step must reference at least one declared material using @id.")
                current_step = {"order": order, "text": description, "materialKeys": refs,
                                "details": [], "expectations": [], "sourceLine": number}
                steps.append(current_step)
            else:
                detail = re.fullmatch(r"  (Detail|Expect): (\S.*)", raw)
                if detail and current_step:
                    current_step["details" if detail[1] == "Detail" else "expectations"].append({"text": detail[2], "sourceLine": number})
                else:
                    error(number, "Use '1. Action with @material'. Attach details with exactly two spaces followed by 'Detail:' or 'Expect:'.")
        else:
            sections[section].append({"text": raw, "sourceLine": number})

    if "Materials" not in seen or not materials:
        error(0, "A nonempty ## Materials section is required.")
    if "Procedure" not in seen or not steps:
        error(0, "A nonempty ## Procedure section is required.")
    if len(materials) > 200 or len(steps) > 1000:
        error(0, "Use at most 200 materials and 1,000 steps.")

    declared = {m["key"] for m in materials}
    # All reference-bearing fields are checked; prose is never converted to targets.
    reference_lines = [(s["sourceLine"], s["text"]) for s in steps]
    reference_lines += [(v["sourceLine"], v["text"]) for s in steps for v in s["details"] + s["expectations"]]
    reference_lines += [(v["sourceLine"], v["text"]) for values in sections.values() for v in values]
    for number, value in reference_lines:
        residue = REFERENCE.sub("", value)
        if "@" in residue:
            error(number, "Malformed @reference. Use lowercase letters, numbers, and hyphens; begin with a letter.")
        for key in REFERENCE.findall(value):
            if key not in declared and key not in invalid_materials and key not in missing_reported:
                error(number, f"Undeclared material @{key}. Add it to ## Materials or correct the reference.")
                missing_reported.add(key)
    # Expect statements may refer only to materials explicitly included in their step.
    for step in steps:
        for entry in step["expectations"]:
            for key in REFERENCE.findall(entry["text"]):
                if key not in step["materialKeys"]:
                    error(entry["sourceLine"], f"Add @{key} to the parent step before using it in Expect.")
    return {"valid": not errors, "errors": errors, "document": None if errors else {
        "formatVersion": 1, "status": "structured", "title": title, "materials": materials, "steps": steps,
        "sections": {k: v for k, v in sections.items() if v},
        "sourceSha256": hashlib.sha256(text.encode()).hexdigest(),
    }}


def tracking_plan(procedure_id, document, steps):
    if not document or document["status"] != "structured":
        return {"schemaVersion": 1, "procedureVersionId": procedure_id, "available": False,
                "analysisEnabled": False, "reason": "Save a valid Medici v1 procedure to define tracking scope.",
                "materials": [], "steps": [], "policy": SCOPE_POLICY}
    used = {key for step in steps for key in step["materialKeys"]}
    return {"schemaVersion": 1, "procedureVersionId": procedure_id, "available": True,
            "analysisEnabled": False, "sourceSha256": document["sourceSha256"],
            "materials": [m for m in document["materials"] if m["key"] in used],
            "steps": [{k: s[k] for k in ("id", "order", "text", "materialKeys", "expectations", "sourceLine")} for s in steps],
            "policy": SCOPE_POLICY}
