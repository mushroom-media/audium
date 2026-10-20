from audium.cli import main

# The guard matters: the scanner's reader processes (forkserver) re-import the main module.
if __name__ == "__main__":
    main()
