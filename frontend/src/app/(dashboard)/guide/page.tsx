'use client';

import React from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { CircleCheckIcon, GithubIcon, KeyIcon, SettingsIcon, FolderIcon } from '@animateicons/react/lucide';
import { buttonVariants } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export default function SetupGuidePage() {
  const steps = [
    {
      title: 'Install the GitHub App',
      icon: GithubIcon,
      content: (
        <div className="space-y-4 text-muted-foreground leading-relaxed">
          <p>
            The first step is to connect Revora to your GitHub account so it can analyze your pull requests. 
            Click the button below to install the <strong>Revora-PR</strong> GitHub application.
          </p>
          <ul className="list-disc list-inside space-y-2 ml-2">
            <li>You will be redirected to GitHub.</li>
            <li>Select <strong>All repositories</strong> or choose <strong>Only select repositories</strong>.</li>
            <li>Click "Install & Authorize".</li>
            <li>You will be automatically redirected back here when finished.</li>
          </ul>
          <div className="pt-4">
            <a 
              href="https://github.com/apps/revora-pr" 
              target="_blank" 
              rel="noopener noreferrer"
              className={cn(buttonVariants({ variant: "default" }), "bg-[#24292e] text-white hover:bg-[#2c3238] border border-white/10 shadow-lg")}
            >
              Install Revora-PR on GitHub ↗
            </a>
          </div>
        </div>
      )
    },
    {
      title: 'Sync Your Repositories',
      icon: FolderIcon,
      content: (
        <div className="space-y-4 text-muted-foreground leading-relaxed">
          <p>
            Once the app is installed, navigate to the <Link href="/repositories" className="text-brand hover:underline font-semibold">Repositories</Link> page.
          </p>
          <p>
            You will see all of the repositories you authorized populated in the list. Revora automatically syncs your repositories in the background. If you just installed the app, it may take a few seconds to appear.
          </p>
        </div>
      )
    },
    {
      title: 'Configure Your API Key',
      icon: KeyIcon,
      content: (
        <div className="space-y-4 text-muted-foreground leading-relaxed">
          <p>
            Revora uses powerful AI models to analyze your code. You need to provide your own API key to power the analysis.
            Currently, <strong>Google Gemini</strong> is the fully supported and available model.
          </p>
          <ol className="list-decimal list-inside space-y-2 ml-2">
            <li>Go to the <Link href="/settings/api-keys" className="text-brand hover:underline font-semibold">API Keys</Link> page.</li>
            <li>Click <strong>Add API Key</strong>.</li>
            <li>Select <strong>Gemini</strong> as the provider.</li>
            <li>Paste your Gemini API key and save it.</li>
          </ol>
        </div>
      )
    },
    {
      title: 'Map a Model to Your Repository',
      icon: SettingsIcon,
      content: (
        <div className="space-y-4 text-muted-foreground leading-relaxed">
          <p>
            Now that you have an API key, you need to tell Revora which model to use for each repository.
          </p>
          <ul className="list-disc list-inside space-y-2 ml-2">
            <li>Go back to the <Link href="/repositories" className="text-brand hover:underline font-semibold">Repositories</Link> page.</li>
            <li>Click the <strong>Settings (gear) icon</strong> next to the repository you want to enable.</li>
            <li>In the Model Selection dropdown, map the repository to the Gemini model you just configured.</li>
            <li>Save your settings.</li>
          </ul>
        </div>
      )
    },
    {
      title: 'Test Your First PR!',
      icon: CircleCheckIcon,
      content: (
        <div className="space-y-4 text-muted-foreground leading-relaxed">
          <p>
            You are completely set up! 🎉
          </p>
          <p>
            To test Revora in action, go to your repository on GitHub and open a new Pull Request. Within seconds, Revora will automatically analyze your code, catch potential bugs, and provide actionable feedback directly as comments on your PR.
          </p>
        </div>
      )
    }
  ];

  return (
    <div className="p-8 max-w-4xl mx-auto w-full min-h-screen">
      <div className="mb-10">
        <h1 className="text-3xl font-bold text-foreground tracking-tight drop-shadow-sm mb-3">How to Use Revora</h1>
        <p className="text-muted-foreground text-lg max-w-2xl">
          Welcome! Follow this quick step-by-step guide to connect your GitHub account, configure your AI models, and start getting automated code reviews.
        </p>
      </div>

      <div className="space-y-8 relative before:absolute before:inset-0 before:ml-5 before:-translate-x-px md:before:mx-auto md:before:translate-x-0 before:h-full before:w-0.5 before:bg-gradient-to-b before:from-transparent before:via-border before:to-transparent">
        {steps.map((step, index) => {
          const Icon = step.icon;
          return (
            <motion.div
              key={index}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, delay: index * 0.1 }}
              className="relative flex items-center justify-between md:justify-normal md:odd:flex-row-reverse group is-active"
            >
              {/* Icon / Marker */}
              <div className="flex items-center justify-center w-10 h-10 rounded-full border-[3px] border-background bg-brand/10 text-brand shrink-0 md:order-1 md:group-odd:-translate-x-1/2 md:group-even:translate-x-1/2 shadow-sm relative z-10">
                <Icon size={18} isAnimated={true} />
              </div>

              {/* Card */}
              <div className="w-[calc(100%-4rem)] md:w-[calc(50%-2.5rem)] p-6 rounded-2xl bg-surface-1/50 backdrop-blur-md border border-border shadow-sm hover:shadow-md transition-shadow">
                <div className="flex items-center gap-3 mb-4">
                  <span className="flex items-center justify-center w-6 h-6 rounded-full bg-brand/20 text-brand text-xs font-bold">
                    {index + 1}
                  </span>
                  <h3 className="font-semibold text-lg text-foreground">{step.title}</h3>
                </div>
                {step.content}
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
