"""
Template Tools - Provide code templates for common tasks.

Includes: get_training_template
"""

from mcp_server_jupyter.observability import get_logger
from mcp_server_jupyter.validation import validated_tool
from mcp_server_jupyter.models import (
    GetTrainingTemplateArgs,
)

logger = get_logger(__name__)


def register_template_tools(mcp, session_manager):
    """Register template tools with the MCP server."""

    @mcp.tool()
    @validated_tool(GetTrainingTemplateArgs)
    async def get_training_template(library: str):
        """
        Get a best-practice code template for training machine learning models.

        Returns a string of Python code that implements checkpointing and training loop
        using the specified library (e.g., 'pytorch', 'tensorflow').

        The template includes:
        - Model definition
        - Training loop with progress tracking
        - Checkpoint saving to ./checkpoints/
        - Best model saving
        - Resume from checkpoint functionality
        """
        if library.lower() == "pytorch":
            return """
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import os
from pathlib import Path

# Create checkpoints directory
checkpoints_dir = Path('./checkpoints')
checkpoints_dir.mkdir(exist_ok=True)

class SimpleModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Linear(784, 128),
            nn.ReLU(),
            nn.Linear(128, 10)
        )

    def forward(self, x):
        return self.layers(x)

def save_checkpoint(model, optimizer, epoch, loss, filename):
    checkpoint = {
        'epoch': epoch,
        'model_state_dict': model.state_dict(),
        'optimizer_state_dict': optimizer.state_dict(),
        'loss': loss,
    }
    torch.save(checkpoint, filename)

def load_checkpoint(model, optimizer, filename):
    if os.path.exists(filename):
        checkpoint = torch.load(filename)
        model.load_state_dict(checkpoint['model_state_dict'])
        optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        epoch = checkpoint['epoch']
        loss = checkpoint['loss']
        return epoch, loss
    return 0, float('inf')

# Initialize model and optimizer
model = SimpleModel()
optimizer = optim.Adam(model.parameters(), lr=0.001)
criterion = nn.CrossEntropyLoss()

# Load from checkpoint if exists
start_epoch, best_loss = load_checkpoint(model, optimizer, checkpoints_dir / 'latest.pt')

# Training loop
num_epochs = 10
for epoch in range(start_epoch, num_epochs):
    # Your training code here
    # for batch in dataloader:
    #     optimizer.zero_grad()
    #     outputs = model(inputs)
    #     loss = criterion(outputs, labels)
    #     loss.backward()
    #     optimizer.step()

    # Mock training for example
    total_loss = 0.5  # Replace with actual loss

    # Save checkpoint every epoch
    save_checkpoint(model, optimizer, epoch, total_loss, checkpoints_dir / 'latest.pt')

    # Save best model
    if total_loss < best_loss:
        best_loss = total_loss
        save_checkpoint(model, optimizer, epoch, total_loss, checkpoints_dir / 'best.pt')

    print(f"Epoch {epoch+1}/{num_epochs}, Loss: {total_loss:.4f}")
"""
        elif library.lower() == "tensorflow":
            return """
import tensorflow as tf
import os
from pathlib import Path

# Create checkpoints directory
checkpoints_dir = Path('./checkpoints')
checkpoints_dir.mkdir(exist_ok=True)

# Define model
model = tf.keras.Sequential([
    tf.keras.layers.Flatten(input_shape=(28, 28)),
    tf.keras.layers.Dense(128, activation='relu'),
    tf.keras.layers.Dense(10, activation='softmax')
])

model.compile(optimizer='adam',
              loss='sparse_categorical_crossentropy',
              metrics=['accuracy'])

# Checkpoint callbacks
checkpoint_callback = tf.keras.callbacks.ModelCheckpoint(
    filepath=str(checkpoints_dir / 'latest.h5'),
    save_best_only=False,
    save_freq='epoch'
)

best_callback = tf.keras.callbacks.ModelCheckpoint(
    filepath=str(checkpoints_dir / 'best.h5'),
    save_best_only=True,
    monitor='loss',
    mode='min'
)

# Load latest checkpoint if exists
latest_checkpoint = checkpoints_dir / 'latest.h5'
if latest_checkpoint.exists():
    model.load_weights(str(latest_checkpoint))
    print("Loaded weights from latest checkpoint")

# Training
# model.fit(train_dataset, epochs=10, callbacks=[checkpoint_callback, best_callback])
print("Training template ready. Uncomment model.fit() with your data.")
"""
        else:
            return f"Unsupported library: {library}. Supported: pytorch, tensorflow"