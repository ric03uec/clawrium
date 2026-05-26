"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface MemoryTabProps {
  agentKey: string;
}

export function MemoryTab({ agentKey }: MemoryTabProps) {
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const queryClient = useQueryClient();

  const { data: memoryInfo, isLoading } = useQuery({
    queryKey: ["memory", agentKey],
    queryFn: () => api.getMemoryFiles(agentKey),
  });

  // Find if the selected file is missing (for create vs edit distinction)
  const selectedFileInfo = memoryInfo?.files?.find(
    (f) => f.relative_path === selectedFile
  );
  const isMissingFile = selectedFileInfo && !selectedFileInfo.exists;

  const { data: fileContent, isLoading: fileLoading } = useQuery({
    queryKey: ["memory-file", agentKey, selectedFile],
    queryFn: () => api.getMemoryFile(agentKey, selectedFile!),
    enabled: !!selectedFile && !isMissingFile, // Don't fetch for missing files
  });

  const saveMutation = useMutation({
    mutationFn: () => api.updateMemoryFile(agentKey, selectedFile!, editContent),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["memory", agentKey] });
      queryClient.invalidateQueries({
        queryKey: ["memory-file", agentKey, selectedFile],
      });
      setIsEditing(false);
      setIsCreating(false);
    },
  });

  if (isLoading) {
    return <div className="p-4 text-muted text-sm">Loading memory info...</div>;
  }

  if (!memoryInfo?.supported) {
    return (
      <div className="flex items-center justify-center h-64 text-muted text-sm">
        Memory is not supported for this agent type.
      </div>
    );
  }

  if (memoryInfo.error) {
    return (
      <div className="flex items-center justify-center h-64 text-muted text-sm">
        Unable to reach agent host. Check SSH connectivity.
      </div>
    );
  }

  return (
    <div className="flex gap-4 p-4 h-[500px]">
      {/* File list */}
      <div className="w-48 shrink-0">
        <Card padding="sm" className="h-full overflow-y-auto">
          <h4 className="text-xs font-semibold text-muted uppercase mb-3">
            Files
          </h4>
          <div className="space-y-1">
            {memoryInfo.files.length === 0 ? (
              <p className="text-xs text-muted">No memory files</p>
            ) : (
              memoryInfo.files.map((file) => (
                <button
                  key={file.relative_path}
                  onClick={() => {
                    setSelectedFile(file.relative_path);
                    setIsEditing(false);
                    setIsCreating(false);
                  }}
                  className={`w-full text-left px-3 py-2 rounded text-sm truncate transition-colors ${
                    selectedFile === file.relative_path
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-secondary hover:bg-surface"
                  } ${!file.exists ? "opacity-60" : ""}`}
                >
                  <span className={!file.exists ? "italic" : ""}>
                    {file.name}
                  </span>
                  {!file.exists && (
                    <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-muted/20 text-muted">
                      missing
                    </span>
                  )}
                </button>
              ))
            )}
          </div>
        </Card>
      </div>

      {/* File content */}
      <div className="flex-1 min-w-0">
        <Card padding="sm" className="h-full flex flex-col">
          {!selectedFile ? (
            <div className="flex-1 flex items-center justify-center text-muted text-sm">
              Select a file to view its content
            </div>
          ) : fileLoading ? (
            <div className="flex-1 flex items-center justify-center text-muted text-sm">
              Loading...
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-sm font-semibold text-primary-text">
                  {selectedFile}
                  {isMissingFile && (
                    <span className="ml-2 text-xs font-normal text-muted">
                      (missing)
                    </span>
                  )}
                </h4>
                <div className="flex gap-2">
                  {isEditing || isCreating ? (
                    <>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setIsEditing(false);
                          setIsCreating(false);
                        }}
                      >
                        Cancel
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => saveMutation.mutate()}
                        disabled={saveMutation.isPending}
                      >
                        {saveMutation.isPending
                          ? "Saving..."
                          : isCreating
                            ? "Create"
                            : "Save"}
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        if (isMissingFile) {
                          setEditContent("");
                          setIsCreating(true);
                        } else {
                          setEditContent(fileContent?.content || "");
                          setIsEditing(true);
                        }
                      }}
                    >
                      {isMissingFile ? "Create" : "Edit"}
                    </Button>
                  )}
                </div>
              </div>
              <div className="flex-1 overflow-y-auto">
                {isEditing || isCreating ? (
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="w-full h-full min-h-[300px] font-mono text-xs p-3 border border-default rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary/20"
                  />
                ) : isMissingFile ? (
                  <div className="flex-1 flex flex-col items-center justify-center text-muted text-sm gap-3">
                    <p>This file does not exist on the agent.</p>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setEditContent("");
                        setIsCreating(true);
                      }}
                    >
                      Create File
                    </Button>
                  </div>
                ) : (
                  <pre className="font-mono text-xs text-secondary p-3 bg-surface rounded-lg whitespace-pre-wrap overflow-auto h-full">
                    {fileContent?.content || "(empty)"}
                  </pre>
                )}
              </div>
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
