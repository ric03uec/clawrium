/**
 * Provider logo registry: maps provider_type to display metadata,
 * icon component, and brand accent color for the topology view.
 */

import { type ComponentType } from "react";

import { AwsIcon } from "@/components/icons/aws";
import { AnthropicIcon } from "@/components/icons/anthropic";
import { OpenAiIcon } from "@/components/icons/openai";
import { GoogleCloudIcon } from "@/components/icons/google-cloud";
import { OpenRouterIcon } from "@/components/icons/openrouter";
import { OllamaIcon } from "@/components/icons/ollama";
import { ZhipuIcon } from "@/components/icons/zhipu";
import { NvidiaIcon } from "@/components/icons/nvidia";

interface IconProps {
  className?: string;
  title?: string;
}

export interface ProviderBrand {
  label: string;
  Icon: ComponentType<IconProps>;
  /** CSS color string for left-border accent and icon tinting */
  accentColor: string;
  /** Whether this is a local inference provider */
  isLocal: boolean;
}

const PROVIDER_BRANDS: Record<string, ProviderBrand> = {
  bedrock: {
    label: "AWS Bedrock",
    Icon: AwsIcon,
    accentColor: "#FF9900",
    isLocal: false,
  },
  anthropic: {
    label: "Anthropic",
    Icon: AnthropicIcon,
    accentColor: "#D4A574",
    isLocal: false,
  },
  openai: {
    label: "OpenAI",
    Icon: OpenAiIcon,
    accentColor: "#171717",
    isLocal: false,
  },
  vertex: {
    label: "Google Vertex",
    Icon: GoogleCloudIcon,
    accentColor: "#4285F4",
    isLocal: false,
  },
  openrouter: {
    label: "OpenRouter",
    Icon: OpenRouterIcon,
    accentColor: "#6366F1",
    isLocal: false,
  },
  ollama: {
    label: "Ollama",
    Icon: OllamaIcon,
    accentColor: "#808080",
    isLocal: true,
  },
  zai: {
    label: "Zhipu AI",
    Icon: ZhipuIcon,
    accentColor: "#1E40AF",
    isLocal: false,
  },
  opencode: {
    label: "OpenCode",
    Icon: OpenAiIcon,
    // Distinct from openai (#171717) so the two render with different
    // border accents in mixed-provider fleets.
    accentColor: "#0F766E",
    isLocal: false,
  },
};

/** NVIDIA-specific brand for local GPU inference (ollama on NVIDIA hardware) */
export const NVIDIA_BRAND: ProviderBrand = {
  label: "NVIDIA · Local",
  Icon: NvidiaIcon,
  accentColor: "#76B900",
  isLocal: true,
};

/**
 * Look up provider brand metadata by provider_type string.
 * Falls back to a generic provider display if unknown.
 */
export function getProviderBrand(providerType: string | null): ProviderBrand {
  if (!providerType) {
    return {
      label: "Provider",
      Icon: OllamaIcon,
      accentColor: "#94A3B8",
      isLocal: false,
    };
  }
  // Use Object.hasOwn to avoid prototype-chain lookups (e.g. "__proto__",
  // "constructor") returning inherited values that break React.createElement.
  if (Object.hasOwn(PROVIDER_BRANDS, providerType)) {
    return PROVIDER_BRANDS[providerType];
  }
  return {
    label: providerType,
    Icon: OllamaIcon,
    accentColor: "#94A3B8",
    isLocal: false,
  };
}

/**
 * Determine if a provider node should display NVIDIA branding.
 * True when provider is ollama AND the host has NVIDIA GPU.
 */
export function isNvidiaLocalInference(
  providerType: string | null,
  hostGpuVendor: string | null | undefined
): boolean {
  if (providerType !== "ollama") return false;
  return hostGpuVendor?.toLowerCase() === "nvidia";
}
