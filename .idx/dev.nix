{ pkgs, ... }: {
  # Add the latest stable Node.js, Python, and Poetry packages to the environment.
  packages = [ 
    pkgs.nodejs
    pkgs.python3
    pkgs.poetry
    pkgs.zeromq
    pkgs.gcc
    pkgs.glibc.dev
  ];
}
