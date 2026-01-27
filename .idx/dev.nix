{ pkgs, ... }: {
  # Add the latest stable Node.js, Python, and Poetry packages to the environment.
  packages = [ 
    pkgs.nodejs 
    pkgs.python3 
    pkgs.poetry
    pkgs.stdenv.cc.cc.lib # Add the C++ standard library for zmq
    pkgs.gcc # Add the GCC toolchain for compiling from source
  ];
}
