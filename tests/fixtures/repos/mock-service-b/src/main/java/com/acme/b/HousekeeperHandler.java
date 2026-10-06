package com.acme.b;

import com.acme.a.OrderGroup;

public class HousekeeperHandler {
    public void handle(OrderGroup group) {
        OrderGroup validated = group;
        OrderGroup result = validated;
        System.out.println(result);
    }
}
