"""Record ONLY a verified Management API project identity, never create a project.

Input must be the real get_project response obtained after confirming access in
the named organization. This offline command does not prove API access itself.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]
from app.academic_cohort.revision6_supabase_target import confirmation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-response", type=Path, required=True)
    parser.add_argument("--confirm-project", required=True)
    parser.add_argument("--ca", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--session-connection", type=Path,
                        help="Nonsecret Connect/session observation; never infer its host")
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(ROOT) or args.output.exists():
        raise ValueError("Confirmation must be NEW and outside the checkout")
    payload = json.loads(args.project_response.read_text(encoding="utf-8"))
    session = (json.loads(args.session_connection.read_text(encoding="utf-8"))
               if args.session_connection is not None else None)
    receipt = confirmation(payload, str(args.ca.resolve()), session_connection=session)
    if args.confirm_project != receipt["project"]["id"]:
        raise ValueError("Real project ref must be explicitly confirmed")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"status":"PROJECT_CONFIRMATION_RECORDED_NOT_DATABASE_APPROVED",
        "project_ref":receipt["project"]["id"],"confirmation_path":str(args.output.resolve()),
        "sha256":hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "database_connected":False,"database_modified":False}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status":"BLOCKED_BY_PROJECT_IDENTITY","error_type":type(error).__name__,
            "message":"Confirm exact healthy dedicated project and CA; no project or database changed."}))
        raise SystemExit(1)
