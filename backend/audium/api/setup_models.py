from pydantic import BaseModel, Field


class SetupMount(BaseModel):
    path: str
    fstype: str
    read_only: bool
    network: bool


class SetupRoot(BaseModel):
    path: str
    track_count: int


class SetupInfo(BaseModel):
    pending: bool = Field(description="The dialog is not finished yet")
    admin_from_env: bool
    roots_from_env: bool = Field(description="AUDIUM_LIBRARY_ROOTS is set")
    music_dir: str
    mounts: list[SetupMount] = Field(description="What is mounted at or below the music dir")
    candidates: list[str] = Field(description="Suggested library folders")
    roots: list[SetupRoot]
    data_persistent: bool | None = Field(description="The data folder survives a new container; null: unknown")
    analysis_available: bool = Field(description="Essentia exists on this platform and AUDIUM_ANALYSIS_ENABLED is on")
    cpus: int
    https: bool
    proxy_not_trusted: bool = Field(
        description="Requests come through a proxy that AUDIUM_TRUSTED_PROXIES does not list"
    )
    utc_offset_minutes: int = Field(description="Time zone of the server")


class ProbeIn(BaseModel):
    path: str = Field(max_length=4096)


class ProbeFormat(BaseModel):
    ext: str
    count: int


class ProbeSample(BaseModel):
    path: str
    title: str | None
    artist: str | None
    album: str | None
    tagged: bool


class ProbeOut(BaseModel):
    path: str
    readable: bool
    complete: bool = Field(description="False: stopped at a limit, the counts are minimums")
    audio_files: int
    size_bytes: int
    formats: list[ProbeFormat]
    image_files: int
    other_files: int
    folders: int
    folders_with_music: int
    folders_with_cover: int
    unreadable_folders: int
    unreadable_examples: list[str]
    samples: list[ProbeSample]
    warnings: list[str] = Field(description="no_audio, mostly_other_files, few_tags, unreadable, unreadable_subfolders")
    owner: str | None = None
    mode: str | None = None
    container_user: str | None = None


class SetupComplete(BaseModel):
    roots: list[str] | None = Field(None, description="Library folders to add. Null: skip, use what is found")


class SetupCompleted(BaseModel):
    job_id: int | None


class ResetIn(BaseModel):
    password: str = Field(max_length=1024, description="The admin's own password, to confirm")
    keep_users: bool = Field(description="Keep the accounts; without: only the admin from AUDIUM_ADMIN_* remains")


class ResetOut(BaseModel):
    needs_setup: bool = Field(description="No account is left: the first admin is created in the browser")
