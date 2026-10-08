"""Drop a stdio worker's identity before executing its configured program."""
import os
import sys


def main():
    uid = int(sys.argv[1])
    if uid not in {11000, 11001, 11002, 11003}:
        raise ValueError("Unknown tool identity")
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
    # setuid clears the worker's capabilities; no-new-privileges is also set
    # on the container. Different UIDs prevent reading sibling environments.
    os.execvpe(sys.argv[2], sys.argv[2:], os.environ)


if __name__ == "__main__":
    main()
