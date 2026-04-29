# Contributing to DryDock

Thanks for checking out DryDock. I’m currently building and maintaining this solo. This initially started as a school-based embedded systems project, and I wanted to take it further as a fully fledged project. Please pardon any dust. The goal is to make filament inventory health and weight tracking as seamless as possible for advanced multi-material setups, or just your personal collection.

Whether you're optimizing the frontend, refining the C++ for the ESP32-S3, or designing a better 3D-printed enclosure, your help is incredibly appreciated.

## The Main Rule: Please Submit PRs
Because this project ties together physical sensors, a web backend, Spoolman, and Klipper, it’s a lot for one person to keep perfectly synced. If you fix a bug, improve a macro, or design a cleaner PCB layout, **please submit a Pull Request back to this main repository.** Keeping everything centralized here makes it much easier to maintain and ensures the rest of the community can actually use your improvements without hunting down dead forks.

## How to Help

### 1. Found a bug?
If something is broken (e.g., sensor noise, Spoolman sync failing, UI glitches), open an Issue. To help me actually fix it, please include:
* Your exact hardware setup (breadboard vs. PCB, which ESP board).
* Steps to reproduce the problem.
* Any relevant logs from the server or serial monitor.

### 2. Have a feature idea?
If you have an idea for a new software feature or a hardware improvement, open an Issue and tag it as an **enhancement**. It’s usually best to open an issue to discuss it *before* you spend hours writing code or doing CAD work, just to make sure it fits with the direction of the project.

### 3. Ready to submit code or hardware?
Standard GitHub flow:
1. **Fork** the repo and make your changes on a new branch.
2. **Test** your stuff. Make sure it doesn't break the existing Spoolman or Klipper integrations, and make sure any 3D models are actually printable.
3. **Submit a PR.** Give me a quick summary of what you changed and why.

## Licensing Agreement
To keep everything legally clean and open for the community: by contributing to DryDock, you agree that your **software/code** contributions fall under the project's **GPLv3 License**, and any **hardware/design** contributions (CAD, STLs, schematics) fall under the **CC BY-NC-SA 4.0 License**.

Want to chat? Send me a message!

Thanks for helping build this!
