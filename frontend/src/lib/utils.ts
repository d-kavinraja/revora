import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export const cardData = [
  {
    id: 1,
    title: "1. Install the GitHub App",
    description: "Connect Revora to your GitHub account to analyze pull requests automatically.",
    color: "rgba(34, 197, 94, 0.8)", // Green
  },
  {
    id: 2,
    title: "2. Sync Your Repositories",
    description: "Revora will sync the repositories you authorized. View them in the Repositories tab.",
    color: "rgba(59, 130, 246, 0.8)", // Blue
  },
  {
    id: 3,
    title: "3. Configure Your API Key",
    description: "Add an API key from Google Gemini, NVIDIA NIM, or Cohere to power the code review.",
    color: "rgba(168, 85, 247, 0.8)", // Purple
  },
  {
    id: 4,
    title: "4. Map a Model to Your Repository",
    description: "Assign your configured AI model to a specific repository in the repository settings.",
    color: "rgba(249, 115, 22, 0.8)", // Orange
  },
  {
    id: 5,
    title: "5. Test Your First PR!",
    description: "Open a Pull Request on GitHub and Revora will automatically review it.",
    color: "rgba(236, 72, 153, 0.8)", // Pink
  }
];
