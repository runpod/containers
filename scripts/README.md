# RunPod Container Scripts

This directory contains utility scripts for managing RunPod container templates.

## Scripts

### update-template-readme.sh

This script updates a RunPod template's README content via the RunPod API.

#### Usage

```bash
./update-template-readme.sh <template_id> <template_path>
```

#### Parameters

- `template_id`: The RunPod template ID to update
- `template_path`: Path to the template directory containing the README.md file

#### Example

```bash
# Update the PyTorch template README
./update-template-readme.sh abc123 official-templates/pytorch

# Update the ComfyUI template README
./update-template-readme.sh def456 official-templates/stable-diffusion-comfyui
```

#### Requirements

- `RUNPOD_API_KEY` environment variable must be set with a valid API key
- Node.js must be installed for JSON escaping
- The README.md file must exist in the specified template path

#### GitHub Actions Integration

To use this script in a GitHub Actions workflow:

1. Copy and customize the template workflow file `.github/workflows/template-update-readme.yml`
2. Set the appropriate template path and template ID secret
3. Add the template ID as a secret in your GitHub repository settings

Example workflow step:

```yaml
- name: Update template README
  env:
    RUNPOD_API_KEY: ${{ secrets.RUNPOD_API_KEY }}
  run: ./scripts/update-template-readme.sh ${{ secrets.TEMPLATE_ID_SECRET }} official-templates/your-template
```
