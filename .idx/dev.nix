{ pkgs, ... }: {
  # Add the latest stable Node.js and Python packages to the environment.
  packages = [ pkgs.nodejs pkgs.python3 ];
}
