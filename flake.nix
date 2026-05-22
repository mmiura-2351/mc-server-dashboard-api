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
            python          # Python 3.13 interpreter (uv が venv 生成時に参照)
            uv              # 主要 package manager
            jdk             # Minecraft server / Java-required tests
            pre-commit      # CLAUDE.md Rule 2/6 で必須
            just            # task runner
            git             # bit / pre-commit が依存
          ];

          # uv が Nix 管理外の Python を取りに行かないよう抑止
          env = {
            UV_PYTHON_DOWNLOADS  = "never";
            UV_PYTHON            = "${python}/bin/python3.13";
            JAVA_HOME            = "${jdk}";
          };

          shellHook = ''
            # Minecraft 起動用 Java パスを Java discovery 機能へ橋渡し
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
