package org.invest.apiorchestrator.controller;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/** Stable operator-facing entry point for the static trading dashboard. */
@Controller
public class DashboardController {

    @GetMapping({"/dashboard", "/dashboard/"})
    public String dashboard() {
        return "redirect:/dashboard/index.html";
    }
}
