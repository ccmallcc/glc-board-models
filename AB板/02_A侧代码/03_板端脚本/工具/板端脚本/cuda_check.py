import torch
print("WSL torch", torch.__version__, "cuda_available", torch.cuda.is_available())
if torch.cuda.is_available():
    print("  设备:", torch.cuda.get_device_name(0))
import compressai
print("  compressai", compressai.__version__)
