"""CAS commits to an isolated report branch; a durable claim precedes each notification."""
import base64
import re
from urllib.parse import quote

import requests


class InvestmentHistory:
    BRANCH = "investment-history"

    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid repository")
        if not token:
            raise ValueError("GitHub token missing")
        self.repository = repository
        self.session = requests.Session()
        self.session.headers.update({"Authorization": "Bearer " + token,
                                     "Accept": "application/vnd.github+json",
                                     "X-GitHub-Api-Version": "2022-11-28"})
        self.root = f"https://api.github.com/repos/{repository}"

    def request(self, method, path, payload=None, missing=False):
        try:
            result = self.session.request(method, self.root + path, json=payload, timeout=(5, 30))
        except requests.RequestException as exc:
            raise RuntimeError("GitHub history transport failure") from exc
        if missing and result.status_code == 404:
            return None
        if not result.ok:
            raise RuntimeError(f"GitHub history HTTP {result.status_code}")
        return result.json()

    def read(self, path):
        result = self.request("GET", f"/contents/{quote(path)}?ref={self.BRANCH}", missing=True)
        return base64.b64decode(result["content"]).decode("utf-8") if result else None

    def save(self, files, message):
        # Ref update without force is a compare-and-swap: concurrent claims cannot both win.
        ref = self.request("GET", f"/git/ref/heads/{self.BRANCH}", missing=True)
        head = ref["object"]["sha"] if ref else None
        payload = {"tree": [{"path": path, "mode": "100644", "type": "blob", "content": content}
                            for path, content in files.items()]}
        if head:
            commit = self.request("GET", f"/git/commits/{head}")
            payload["base_tree"] = commit["tree"]["sha"]
        tree = self.request("POST", "/git/trees", payload)
        commit = self.request("POST", "/git/commits", {"message": message, "tree": tree["sha"],
                                                      "parents": [head] if head else []})
        if head:
            self.request("PATCH", f"/git/refs/heads/{self.BRANCH}", {"sha": commit["sha"], "force": False})
        else:
            self.request("POST", "/git/refs", {"ref": "refs/heads/" + self.BRANCH, "sha": commit["sha"]})
        return commit["sha"]

    def url(self, path):
        return f"https://github.com/{self.repository}/blob/{self.BRANCH}/{quote(path)}"
