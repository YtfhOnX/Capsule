"""Entry point for the packaged .exe."""
import sys

if len(sys.argv) == 1:
    from capsule.launcher import main
    main()
else:
    from capsule.app import main
    sys.exit(main())
