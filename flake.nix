{
  description = "mc-server-dashboard-api dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        python = pkgs.python313;
        jdk    = pkgs.jdk21;
      in {
        devShells.default = pkgs.mkShell {
          name = "mc-server-dashboard-api";

          packages = with pkgs; [
            python          # Python 3.13 interpreter (used by uv when creating the venv)
            uv              # primary package manager
            jdk             # Minecraft server / Java-required tests
            pre-commit      # required by CLAUDE.md Rule 2/6
            just            # task runner
            git             # required by bit / pre-commit
          ];

          # Prevent uv from fetching a Python outside of Nix.
          env = {
            UV_PYTHON_DOWNLOADS  = "never";
            UV_PYTHON            = "${python}/bin/python3.13";
            JAVA_HOME            = "${jdk}";
          };

          shellHook = ''
            # Expose the Minecraft-launch Java path to the Java discovery feature.
            export JAVA_21_PATH="${jdk}/bin/java"

            echo "mc-server-dashboard-api devShell"
            echo "  python : $(python3 --version)"
            echo "  uv     : $(uv --version)"
            echo "  java   : $(java -version 2>&1 | head -n1)"
            echo ""
            echo "Next: 'uv sync --group dev' then 'uv run pre-commit install'"
          '';
        };
      });
}
