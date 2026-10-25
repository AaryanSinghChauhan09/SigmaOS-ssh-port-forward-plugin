    # SigmaOS-ssh-port-forward-plugin

    SSH port-forward manager plugin

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/omacom/omarchy-port-forward-plugin

    ## Design principles applied
    - **Plan Before Act**
- **Fail-Fast**
- **Defensive Programming**
- **KISS**
- **Least Astonishment**
- **Deterministic Testing**

    ## Usage
    Verbs: `add, list, start-plan, stop, test`

    ```
    $ sigma-ssh-forward add "local 8080:web.internal:80" --via alice@bastion.example.com
$ sigma-ssh-forward list
local-8080  local  8080 -> web.internal:80  via alice@bastion.example.com  on
$ sigma-ssh-forward start-plan
ssh -N -L 8080:web.internal:80 alice@bastion.example.com
$ sigma-ssh-forward stop local-8080
$ sigma-ssh-forward test
ok: 1 forward(s) valid

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
