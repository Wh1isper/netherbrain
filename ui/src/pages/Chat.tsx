import { useParams } from "react-router-dom";

export default function Chat() {
  const { id } = useParams<{ id: string }>();

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        {id ? (
          <p>Loading conversation {id}...</p>
        ) : (
          <div className="text-center space-y-2">
            <p className="text-lg font-medium text-foreground">Netherbrain</p>
            <p className="text-sm">Select a conversation or start a new chat.</p>
          </div>
        )}
      </div>
    </div>
  );
}
