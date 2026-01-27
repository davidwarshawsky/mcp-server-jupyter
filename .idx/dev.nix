{ pkgs, ... }: {
  packages = [
    pkgs.python3
    pkgs.poetry
  ];

  # Removed the 'env' block containing LD_LIBRARY_PATH 
  # because referencing stdenv.cc.cc.lib there forces the download.

  idx = {
    workspace = {
      # Restored the automated setup
      onCreate = {
        setup = ''
          # Configure poetry to create the venv inside the project
          poetry config virtualenvs.in-project true
          
          # Navigate to your project folder
          cd tools/mcp-server-jupyter
          
          # Install dependencies automatically
          poetry install
        '';
      };
      
      # Ensure the venv is activated when you open the terminal
      onStart = {
        activate = ''
          cd tools/mcp-server-jupyter
          source .venv/bin/activate
        '';
      };
    };
  };
}