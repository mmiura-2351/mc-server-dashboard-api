{
  description = "mc-server-dashboard-api development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        devShells.default = pkgs.mkShell {
          packages = with pkgs; [
            go_1_23
            gotools
            sqlc
            goose
            golangci-lint
          ];

          shellHook = ''
            echo "mc-server-dashboard-api dev environment ready"
            go version
          '';
        };
      }
    );
}
