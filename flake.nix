{
  description = "device control development environment";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs?ref=nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
      in
      {
        devShells.default = pkgs.mkShell {
          name = "device-control";

          packages = [
            pkgs.python3
            pkgs.uv
          ];

          shellHook = ''
            echo "device_control development environment"
            echo "Run: uv sync"
          '';
        };
      }
    );
}
