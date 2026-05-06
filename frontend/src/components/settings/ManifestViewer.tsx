export function ManifestViewer({ value }: { value: unknown }) {
  return (
    <pre className="manifest-viewer" aria-label="Manifest data">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
